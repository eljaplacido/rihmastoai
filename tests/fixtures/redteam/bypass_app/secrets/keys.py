"""Framework secrets under classic names, a lowercase hex token, and a short password. All made up."""

SECRET_KEY = "k9#Qz2!vX7@pLm4$wR8^tY1&uN6*eB3"  # seeded: RT-SECRET-ENTROPY
ENCRYPTION_KEY = "Vq7#mZ2!kP9xL4wR8tY1uN6eB3cH5sJ0"  # seeded: RT-SECRET-ENTROPY
DB_PASS = "Wm4!rT8#qZ2xK7pL"  # seeded: RT-SECRET-ENTROPY
DB_PASSWORD = "Tr0ub4dor&3"  # seeded: RT-SECRET-ENTROPY
API_TOKEN = "f3a9c2e81b7d4f60a3f9c2e81b7d4f61"  # seeded: RT-SECRET-ENTROPY


def configure(app):
    app.secret_key = "k9#Qz2!vX7@pLm4$wR8^tY1&uN6*eB3"  # seeded: RT-SECRET-ENTROPY
