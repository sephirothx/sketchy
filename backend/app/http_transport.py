"""The HTTP/1.1 transport: httptools, with the request-head bound h11 had.

`app.server` names httptools as the HTTP parser (#977): it costs the event loop
~13 us a request against h11's ~75. But h11 bounds how much of a request head
it will hold before refusing (16 KiB, uvicorn's `h11_max_incomplete_event_size`
default), and httptools holds a header until it is complete, however long:
measured, one unauthenticated connection sending a 300 MB header took the
process from 39 MB to 7.35 GB. This subclass puts the same bound back.

Two checks, because httptools reports a header only once it is complete. The
fields as they complete - the URL and every name and value - are summed, and a
head past `MAX_REQUEST_HEAD_BYTES` is refused there, which catches one that
arrived in a single read. And the bytes received while a head is still open
are counted across reads, which catches the one that is never completed: that
is where the memory went. Either answers **431** and closes. The read count is
taken after a read is parsed, so a body arriving in the same read as its
headers is never taken for head.
"""
from __future__ import annotations

from uvicorn.protocols.http.httptools_impl import STATUS_LINE, HttpToolsProtocol

#: The request line and headers of one request, together. h11's default, so
#: the parser change moves no limit a client could have met.
MAX_REQUEST_HEAD_BYTES = 16 * 1024


class _HeadTooLarge(Exception):
    """Raised from a parser callback; httptools hands it on as a parser error."""


class BoundedHttpToolsProtocol(HttpToolsProtocol):
    """`HttpToolsProtocol` that refuses a request head past the bound."""

    def connection_made(self, transport) -> None:  # type: ignore[override]
        super().connection_made(transport)
        self._head_open = True
        self._head_bytes = 0
        self._field_bytes = 0
        self._head_too_large = False

    def on_message_begin(self) -> None:
        super().on_message_begin()
        self._head_open = True
        self._head_bytes = 0
        self._field_bytes = 0

    def _count_field(self, size: int) -> None:
        self._field_bytes += size
        if self._field_bytes > MAX_REQUEST_HEAD_BYTES:
            self._head_too_large = True
            raise _HeadTooLarge

    def on_url(self, url: bytes) -> None:
        self._count_field(len(url))
        super().on_url(url)

    def on_header(self, name: bytes, value: bytes) -> None:
        self._count_field(len(name) + len(value) + 4)
        super().on_header(name, value)

    def send_400_response(self, msg: str) -> None:
        # uvicorn answers every parser error with a 400; the one this class
        # raised says what it is.
        if self._head_too_large:
            self._send_431()
            return
        super().send_400_response(msg)

    def on_headers_complete(self) -> None:
        self._head_open = False
        super().on_headers_complete()

    def data_received(self, data: bytes) -> None:
        if self._head_open:
            self._head_bytes += len(data)
        super().data_received(data)
        if (
            self._head_open
            and self._head_bytes > MAX_REQUEST_HEAD_BYTES
            and not self.transport.is_closing()
        ):
            self._head_too_large = True
            self._send_431()

    def _send_431(self) -> None:
        message = b"Request header fields too large."
        content = [STATUS_LINE[431]]
        for name, value in self.server_state.default_headers:
            content.extend([name, b": ", value, b"\r\n"])
        content.extend(
            [
                b"content-type: text/plain; charset=utf-8\r\n",
                b"content-length: " + str(len(message)).encode("ascii") + b"\r\n",
                b"connection: close\r\n",
                b"\r\n",
                message,
            ]
        )
        self.transport.write(b"".join(content))
        self.transport.close()
