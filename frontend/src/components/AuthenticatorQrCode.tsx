import { useMemo } from "react";
import qrcode from "qrcode-generator";

/**
 * The enrolment key as something a phone camera can read.
 *
 * Drawn as an inline SVG from the module grid rather than through the
 * library's own `createSvgTag`, for two reasons: the colours come from the
 * theme so it stays legible in dark mode (a QR reader needs contrast, not
 * black specifically), and one `<path>` of rectangles is far less DOM than a
 * table or an element per module.
 *
 * Loaded on demand: the encoder is ~24 kB and the overwhelming majority of
 * page loads never open this dialog, so it stays out of the bundle everyone
 * else downloads.
 *
 * Error correction level M, which tolerates about 15% of the code being
 * obscured — enough for a camera at an angle, without making the grid so
 * dense that a small screen renders it unscannable.
 */
export default function AuthenticatorQrCode({ uri, label }: { uri: string; label: string }) {
  const { path, size } = useMemo(() => {
    const code = qrcode(0, "M");
    code.addData(uri);
    code.make();
    const count = code.getModuleCount();
    const parts: string[] = [];
    for (let row = 0; row < count; row += 1) {
      for (let column = 0; column < count; column += 1) {
        if (code.isDark(row, column)) parts.push(`M${column} ${row}h1v1h-1z`);
      }
    }
    return { path: parts.join(""), size: count };
  }, [uri]);

  // One module of quiet zone on each side. The spec asks for four; the white
  // card the code sits on supplies the rest visually, and the extra padding
  // here would only shrink the modules.
  const bounds = size + 2;
  return (
    <svg
      className="two-factor-qr"
      viewBox={`-1 -1 ${bounds} ${bounds}`}
      role="img"
      aria-label={label}
      shapeRendering="crispEdges"
    >
      <rect x={-1} y={-1} width={bounds} height={bounds} fill="var(--qr-light)" />
      <path d={path} fill="var(--qr-dark)" />
    </svg>
  );
}
