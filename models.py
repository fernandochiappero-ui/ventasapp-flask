# models.py
#
# Aquí definimos las "tablas" de la base de datos como clases de Python.
# Esto se llama ORM (Object-Relational Mapping): cada clase = una tabla,
# cada atributo = una columna, cada instancia de la clase = una fila.
# SQLAlchemy se encarga de traducir esto a SQL por nosotros.

from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class Usuario(UserMixin, db.Model):
    """
    Representa a quien puede ingresar al sistema (login).
    UserMixin le agrega automáticamente los métodos que Flask-Login
    necesita (is_authenticated, is_active, get_id, etc.).
    """
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="administrador")

    @property
    def es_administrador(self):
        return self.rol == "administrador"

    @property
    def es_vendedor(self):
        return self.rol == "vendedor"

    def set_password(self, password_plano):
        # NUNCA se guarda la contraseña como texto plano.
        # generate_password_hash la convierte en un "hash" irreversible.
        self.password_hash = generate_password_hash(password_plano)

    def check_password(self, password_plano):
        # Compara el texto ingresado contra el hash guardado.
        return check_password_hash(self.password_hash, password_plano)


class Cliente(db.Model):
    """Un cliente de la tienda/negocio."""
    __tablename__ = "clientes"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    telefono = db.Column(db.String(50))
    direccion = db.Column(db.String(200))
    notas = db.Column(db.String(300))
    activo = db.Column(db.Boolean, default=True, nullable=False)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    # "relationship" no crea una columna: le dice a SQLAlchemy cómo
    # navegar de un Cliente a sus Ventas y Movimientos relacionados,
    # por ejemplo cliente.movimientos te da la lista completa.
    ventas = db.relationship("Venta", backref="cliente", lazy=True)
    movimientos = db.relationship(
        "MovimientoCC", backref="cliente", lazy=True,
        order_by="MovimientoCC.fecha"
    )

    @property
    def saldo(self):
        """
        Calcula el saldo actual de la cuenta corriente del cliente:
        suma de ventas a cuenta (deuda) menos suma de pagos (abonos).
        Un saldo positivo = el cliente te debe esa plata.
        """
        total = 0.0
        for m in self.movimientos:
            if m.tipo == "venta":
                total += m.monto
            else:  # "pago"
                total -= m.monto
        return round(total, 2)


class Venta(db.Model):
    """Una venta diaria. Puede ser en efectivo o a cuenta corriente."""
    __tablename__ = "ventas"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    fecha = db.Column(db.Date, default=date.today, nullable=False)
    descripcion = db.Column(db.String(200))
    monto = db.Column(db.Float, nullable=False)
    forma_pago = db.Column(db.String(20), nullable=False)  # "efectivo" o "cuenta_corriente"
    creado = db.Column(db.DateTime, default=datetime.utcnow)


class MovimientoCC(db.Model):
    """
    Un movimiento de la cuenta corriente de un cliente.
    tipo = "venta"  -> aumenta la deuda (se generó automáticamente
                        al cargar una venta a cuenta corriente)
    tipo = "pago"   -> disminuye la deuda (el cliente abonó/pagó)
    Guardamos cada movimiento por separado (en vez de solo un número
    de saldo) para poder mostrar el historial completo y hacer
    reportes por rango de fechas.
    """
    __tablename__ = "movimientos_cc"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    venta_id = db.Column(db.Integer, db.ForeignKey("ventas.id"), nullable=True)
    fecha = db.Column(db.Date, default=date.today, nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # "venta" | "pago"
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(200))
    creado = db.Column(db.DateTime, default=datetime.utcnow)
