"""Stock levels per item, and the audit log of who changed one."""

import logging

log = logging.getLogger(__name__)


def level(stock, sku):
    """The quantity of ``sku`` in stock: 0 when it is not stocked."""
    if not sku:
        raise ValueError("sku is required")
    return int(stock.get(sku, 0))


def change(stock, audit_log, sku, quantity, email):
    """Set the quantity of ``sku`` and record who changed it."""
    if quantity < 0:
        raise ValueError("a quantity is never negative")
    before = level(stock, sku)
    stock[sku] = quantity
    audit_log.append({"sku": sku, "from": before, "to": quantity, "email": email})
    log.info("stock of %s changed from %s to %s", sku, before, quantity)
    return quantity
