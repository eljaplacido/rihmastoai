"""The Rihma cockpit: a loopback-only web page over the kernel, by persona (FR-T1, FR-M3).

Rihma is the factory; Gnomon is the engine underneath it (D-0010). `cockpit.server` serves the
page and a JSON API. Every read and write goes through the kernel modules. The Inbox is the
only write path for human decisions (FR-M6).
"""
