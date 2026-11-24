"""The service's routes: each handler takes the stock and the request's path, and answers a status and a body."""

from app.stock import level


class Router:
    def __init__(self):
        self.routes = {}

    def get(self, path):
        def add(handler):
            self.routes[("GET", path)] = handler
            return handler
        return add


app = Router()


@app.get("/health")
def health(stock, path):
    return 200, {"status": "ok", "items": len(stock)}


@app.get("/stock")
def stock_level(stock, path):
    sku = path.rsplit("/", 1)[-1]
    return 200, {"sku": sku, "quantity": level(stock, sku)}
