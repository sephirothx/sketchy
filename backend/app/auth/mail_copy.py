"""The five messages Sketchy sends, in each language it is read in.

Email is the one place the server legitimately writes prose, because there is
no client at the other end to write it (R-I18N-01) - and therefore the only
place the reader's language has to be *stored* rather than resolved. The row
carries it; this module turns it into words.

Still no template engine, for the reason `mail.py` gave when there was one
language: five messages, four lines each. What has changed is that there are
now seven of them, so the shape is a table rather than a function - the
assembly lives once, in `render()`, and each language supplies only words.
That also keeps the suspension message honest: its *"It lifts on …"* and
*"recorded as …"* clauses are built inside the locale, not handed to it as
English fragments to drop into a sentence (R-I18N-02).

Two of the five matter most here. A **suspension** notice is the only message
that reaches an account which can no longer sign in, and a **password reset**
is read by somebody already having a bad day. Those are the worst two to send
in a language the reader did not choose.

Dates are written **ISO** - `2026-09-11` - in every language. Month names
would need a locale database this project does not carry, and a date nobody
can misread beats one that is charming in English and wrong everywhere else.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MailCopy:
    """One language's words for the five messages.

    Every field is a whole sentence or a whole clause in that language: a
    translation moves them where its own grammar wants them, which is why the
    suspension's parts are separate fields rather than one string with a hole
    English happens to put in the middle.
    """

    # `Hi {name},` - and the whole greeting for somebody whose name is not
    # known, because "Hola ," is not a sentence and patching one up in the
    # renderer would be English grammar applied to six other languages.
    greeting: str
    greeting_unnamed: str

    verify_subject: str
    verify_body: str

    reset_subject: str
    reset_body: str

    changed_subject: str
    changed_body: str

    banned_subject: str
    banned_body: str
    banned_default_reason: str
    banned_about: str
    banned_until: str
    banned_forever: str

    hidden_subject: str
    hidden_body: str
    hidden_default_what: str
    # The *kind* of thing hidden, named in this language. The server used to
    # compose "A prompt you shared" and hand it over as a phrase, which is a
    # fragment in every language but the one that wrote it (R-I18N-02).
    hidden_prompt: str
    hidden_prompt_list: str


EN = MailCopy(
    greeting="Hi {name},",
    greeting_unnamed="Hi there,",
    verify_subject="Confirm your Sketchy email address",
    verify_body=(
        "Confirm this address so you can recover your account if you ever "
        "lose your password:\n\n{link}\n\n"
        "The link works for one day. If you did not ask for this, nothing has "
        "changed and you can ignore this message."
    ),
    reset_subject="Reset your Sketchy password",
    reset_body=(
        "Choose a new password here:\n\n{link}\n\n"
        "The link works for one hour and can be used once. If you did not ask "
        "for it, your password has not changed and you can ignore this message."
    ),
    changed_subject="Your Sketchy password was changed",
    changed_body=(
        "Your password has just been changed and every signed-in device has "
        "been signed out.\n\n"
        "If this was not you, reset your password immediately at {link}."
    ),
    banned_subject="Your Sketchy account has been suspended",
    banned_body=(
        "Your account has been suspended for {reason}.{about}\n{when}\n\n"
        "Signing in will show you what it was about."
    ),
    banned_default_reason="a breach of the rules",
    banned_about=" It was recorded as {category}.",
    banned_until="It lifts on {date}.",
    banned_forever="This suspension does not expire on its own.",
    hidden_subject="Content of yours was hidden",
    hidden_body="{what} has been hidden after a moderation review.",
    hidden_default_what="some content you shared",
    hidden_prompt="A prompt you shared",
    hidden_prompt_list="A prompt list you shared",
)

DE = MailCopy(
    greeting="Hallo {name},",
    greeting_unnamed="Hallo,",
    verify_subject="Bestätige deine Sketchy-E-Mail-Adresse",
    verify_body=(
        "Bestätige diese Adresse, damit du dein Konto wiederherstellen kannst, "
        "falls du jemals dein Passwort verlierst:\n\n{link}\n\n"
        "Der Link gilt einen Tag. Wenn du das nicht angefordert hast, hat sich "
        "nichts geändert und du kannst diese Nachricht ignorieren."
    ),
    reset_subject="Setze dein Sketchy-Passwort zurück",
    reset_body=(
        "Wähle hier ein neues Passwort:\n\n{link}\n\n"
        "Der Link gilt eine Stunde und lässt sich einmal verwenden. Wenn du ihn "
        "nicht angefordert hast, hat sich dein Passwort nicht geändert und du "
        "kannst diese Nachricht ignorieren."
    ),
    changed_subject="Dein Sketchy-Passwort wurde geändert",
    changed_body=(
        "Dein Passwort wurde gerade geändert, und alle angemeldeten Geräte "
        "wurden abgemeldet.\n\n"
        "Wenn du das nicht warst, setze dein Passwort sofort hier zurück: {link}."
    ),
    banned_subject="Dein Sketchy-Konto wurde gesperrt",
    banned_body=(
        "Dein Konto wurde gesperrt wegen {reason}.{about}\n{when}\n\n"
        "Beim Anmelden siehst du, worum es ging."
    ),
    banned_default_reason="eines Regelverstoßes",
    banned_about=" Erfasst wurde es als {category}.",
    banned_until="Sie endet am {date}.",
    banned_forever="Diese Sperre endet nicht von selbst.",
    hidden_subject="Ein Inhalt von dir wurde ausgeblendet",
    hidden_body="{what} wurde nach einer Moderationsprüfung ausgeblendet.",
    hidden_default_what="Ein von dir geteilter Inhalt",
    hidden_prompt="Ein von dir geteilter Begriff",
    hidden_prompt_list="Eine von dir geteilte Begriffsliste",
)

ES = MailCopy(
    greeting="Hola {name}:",
    greeting_unnamed="Hola:",
    verify_subject="Confirma tu correo de Sketchy",
    verify_body=(
        "Confirma esta dirección para poder recuperar tu cuenta si algún día "
        "pierdes la contraseña:\n\n{link}\n\n"
        "El enlace sirve un día. Si no lo has pedido, no ha cambiado nada y "
        "puedes ignorar este mensaje."
    ),
    reset_subject="Restablece tu contraseña de Sketchy",
    reset_body=(
        "Elige aquí una contraseña nueva:\n\n{link}\n\n"
        "El enlace sirve una hora y se puede usar una vez. Si no lo has pedido, "
        "tu contraseña no ha cambiado y puedes ignorar este mensaje."
    ),
    changed_subject="Tu contraseña de Sketchy ha cambiado",
    changed_body=(
        "Acabas de cambiar tu contraseña y se ha cerrado la sesión en todos los "
        "dispositivos.\n\n"
        "Si no has sido tú, restablece la contraseña ahora mismo en {link}."
    ),
    banned_subject="Tu cuenta de Sketchy ha sido suspendida",
    banned_body=(
        "Tu cuenta ha sido suspendida por {reason}.{about}\n{when}\n\n"
        "Al iniciar sesión verás de qué se trataba."
    ),
    banned_default_reason="incumplir las reglas",
    banned_about=" Se registró como {category}.",
    banned_until="Se levanta el {date}.",
    banned_forever="Esta suspensión no caduca por sí sola.",
    hidden_subject="Se ha ocultado contenido tuyo",
    hidden_body="{what} se ha ocultado tras una revisión de moderación.",
    hidden_default_what="Algo que compartiste",
    hidden_prompt="Una palabra que compartiste",
    hidden_prompt_list="Una lista de palabras que compartiste",
)

FR = MailCopy(
    greeting="Bonjour {name},",
    greeting_unnamed="Bonjour,",
    verify_subject="Confirme ton adresse e-mail Sketchy",
    verify_body=(
        "Confirme cette adresse pour pouvoir récupérer ton compte si tu perds "
        "un jour ton mot de passe :\n\n{link}\n\n"
        "Le lien est valable un jour. Si tu n’as rien demandé, rien n’a changé "
        "et tu peux ignorer ce message."
    ),
    reset_subject="Réinitialise ton mot de passe Sketchy",
    reset_body=(
        "Choisis un nouveau mot de passe ici :\n\n{link}\n\n"
        "Le lien est valable une heure et sert une seule fois. Si tu ne l’as "
        "pas demandé, ton mot de passe n’a pas changé et tu peux ignorer ce "
        "message."
    ),
    changed_subject="Ton mot de passe Sketchy a été changé",
    changed_body=(
        "Ton mot de passe vient d’être changé et tous les appareils connectés "
        "ont été déconnectés.\n\n"
        "Si ce n’était pas toi, réinitialise-le immédiatement sur {link}."
    ),
    banned_subject="Ton compte Sketchy a été suspendu",
    banned_body=(
        "Ton compte a été suspendu pour {reason}.{about}\n{when}\n\n"
        "En te connectant, tu verras de quoi il s’agissait."
    ),
    banned_default_reason="non-respect des règles",
    banned_about=" Cela a été enregistré comme {category}.",
    banned_until="Elle est levée le {date}.",
    banned_forever="Cette suspension ne prend pas fin d’elle-même.",
    hidden_subject="Un contenu à toi a été masqué",
    hidden_body="{what} a été masqué après une décision de modération.",
    hidden_default_what="Un contenu que tu as partagé",
    hidden_prompt="Un mot que tu as partagé",
    hidden_prompt_list="Une liste de mots que tu as partagée",
)

IT = MailCopy(
    greeting="Ciao {name},",
    greeting_unnamed="Ciao,",
    verify_subject="Conferma il tuo indirizzo email di Sketchy",
    verify_body=(
        "Conferma questo indirizzo per poter recuperare il tuo account se un "
        "giorno perdi la password:\n\n{link}\n\n"
        "Il link vale un giorno. Se non l’hai richiesto, non è cambiato niente "
        "e puoi ignorare questo messaggio."
    ),
    reset_subject="Reimposta la tua password di Sketchy",
    reset_body=(
        "Scegli qui una nuova password:\n\n{link}\n\n"
        "Il link vale un’ora e si può usare una volta sola. Se non l’hai "
        "richiesto, la tua password non è cambiata e puoi ignorare questo "
        "messaggio."
    ),
    changed_subject="La tua password di Sketchy è stata cambiata",
    changed_body=(
        "La tua password è appena stata cambiata e tutti i dispositivi "
        "connessi sono stati disconnessi.\n\n"
        "Se non sei stato tu, reimpostala subito su {link}."
    ),
    banned_subject="Il tuo account Sketchy è stato sospeso",
    banned_body=(
        "Il tuo account è stato sospeso per {reason}.{about}\n{when}\n\n"
        "Accedendo vedrai di cosa si trattava."
    ),
    banned_default_reason="una violazione delle regole",
    banned_about=" È stato registrato come {category}.",
    banned_until="Finisce il {date}.",
    banned_forever="Questa sospensione non finisce da sola.",
    hidden_subject="Un tuo contenuto è stato nascosto",
    hidden_body="{what} è stato nascosto dopo una verifica di moderazione.",
    hidden_default_what="Un contenuto che hai condiviso",
    hidden_prompt="Una parola che hai condiviso",
    hidden_prompt_list="Una lista di parole che hai condiviso",
)

NL = MailCopy(
    greeting="Hoi {name},",
    greeting_unnamed="Hoi,",
    verify_subject="Bevestig je Sketchy-e-mailadres",
    verify_body=(
        "Bevestig dit adres zodat je je account kunt herstellen als je ooit je "
        "wachtwoord kwijtraakt:\n\n{link}\n\n"
        "De link werkt één dag. Als je hier niet om gevraagd hebt, is er niets "
        "veranderd en kun je dit bericht negeren."
    ),
    reset_subject="Herstel je Sketchy-wachtwoord",
    reset_body=(
        "Kies hier een nieuw wachtwoord:\n\n{link}\n\n"
        "De link werkt een uur en is één keer te gebruiken. Als je er niet om "
        "gevraagd hebt, is je wachtwoord niet veranderd en kun je dit bericht "
        "negeren."
    ),
    changed_subject="Je Sketchy-wachtwoord is gewijzigd",
    changed_body=(
        "Je wachtwoord is zojuist gewijzigd en elk ingelogd apparaat is "
        "uitgelogd.\n\n"
        "Als jij dit niet was, herstel je wachtwoord dan meteen op {link}."
    ),
    banned_subject="Je Sketchy-account is geschorst",
    banned_body=(
        "Je account is geschorst wegens {reason}.{about}\n{when}\n\n"
        "Als je inlogt, zie je waar het over ging."
    ),
    banned_default_reason="het overtreden van de regels",
    banned_about=" Het is vastgelegd als {category}.",
    banned_until="De schorsing loopt af op {date}.",
    banned_forever="Deze schorsing loopt niet vanzelf af.",
    hidden_subject="Iets van jou is verborgen",
    hidden_body="{what} is verborgen na een beoordeling door een moderator.",
    hidden_default_what="Iets dat je gedeeld hebt",
    hidden_prompt="Een woord dat je gedeeld hebt",
    hidden_prompt_list="Een woordenlijst die je gedeeld hebt",
)

PT = MailCopy(
    greeting="Olá {name},",
    greeting_unnamed="Olá,",
    verify_subject="Confirma o teu e-mail do Sketchy",
    verify_body=(
        "Confirma este endereço para poderes recuperar a tua conta se um dia "
        "perderes a palavra-passe:\n\n{link}\n\n"
        "A ligação serve um dia. Se não pediste isto, não mudou nada e podes "
        "ignorar esta mensagem."
    ),
    reset_subject="Repõe a tua palavra-passe do Sketchy",
    reset_body=(
        "Escolhe aqui uma palavra-passe nova:\n\n{link}\n\n"
        "A ligação serve uma hora e pode ser usada uma vez. Se não a pediste, "
        "a tua palavra-passe não mudou e podes ignorar esta mensagem."
    ),
    changed_subject="A tua palavra-passe do Sketchy foi alterada",
    changed_body=(
        "A tua palavra-passe acabou de ser alterada e todos os dispositivos "
        "com sessão iniciada foram desligados.\n\n"
        "Se não foste tu, repõe a palavra-passe já em {link}."
    ),
    banned_subject="A tua conta do Sketchy foi suspensa",
    banned_body=(
        "A tua conta foi suspensa por {reason}.{about}\n{when}\n\n"
        "Ao iniciares sessão vais ver do que se tratava."
    ),
    banned_default_reason="quebra das regras",
    banned_about=" Foi registado como {category}.",
    banned_until="Termina a {date}.",
    banned_forever="Esta suspensão não termina por si.",
    hidden_subject="Um conteúdo teu foi escondido",
    hidden_body="{what} foi escondido depois de uma análise de moderação.",
    hidden_default_what="Algo que partilhaste",
    hidden_prompt="Uma palavra que partilhaste",
    hidden_prompt_list="Uma lista de palavras que partilhaste",
)

COPY: dict[str, MailCopy] = {
    "en": EN,
    "de": DE,
    "es": ES,
    "fr": FR,
    "it": IT,
    "nl": NL,
    "pt": PT,
}


def copy_for(locale: str | None) -> MailCopy:
    """The words for `locale`, or English for one nobody has written.

    English rather than nothing, for the same reason the rules page falls
    back: a message a recipient cannot read is worse than one in a language
    they did not pick.
    """
    return COPY.get(str(locale or "").lower(), EN)
