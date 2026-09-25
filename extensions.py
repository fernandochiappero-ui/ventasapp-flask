# extensions.py
#
# Este archivo existe solo para evitar "importaciones circulares".
# Problema típico en Flask: app.py necesita a "db" (definido en models.py),
# pero models.py necesita a "db" también, y si cada uno importa del otro
# Python se confunde. La solución clásica es crear los objetos "db" y
# "login_manager" en un archivo aparte (este) que tanto app.py como
# models.py pueden importar sin problemas.

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
