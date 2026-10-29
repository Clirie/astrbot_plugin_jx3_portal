from dataclasses import dataclass

@dataclass
class ImageReply:
    path: str
    extra_paths: tuple[str, ...] = ()
    caption: str = ""
    menu: object = None

@dataclass
class MessageParts:
    parts: list[dict]

@dataclass
class PendingReply:
    text: str
    load: object
    on_sent: object = None
    menu: object = None
