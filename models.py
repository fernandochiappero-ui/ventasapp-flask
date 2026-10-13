# models.py
#
# Aquí definimos las "tablas" de la base de datos como clases de Python.
# Esto se llama ORM (Object-Relational Mapping): cada clase = una tabla,
# cada atributo = una columna, cada instancia de la clase = una fila.
# SQLAlchemy se encarga de traducir esto a SQL por nosotros.

from datetime import datetime, date
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")


def ahora_argentina():
    return datetime.now(ZONA_HORARIA).replace(tzinfo=None)


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
    creado = db.Column(db.DateTime, default=ahora_argentina)

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
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    fecha = db.Column(db.Date, default=date.today, nullable=False)
    descripcion = db.Column(db.String(200))
    monto = db.Column(db.Float, nullable=False)
    forma_pago = db.Column(db.String(20), nullable=False)  # "efectivo" o "cuenta_corriente"
    creado = db.Column(db.DateTime, default=ahora_argentina)
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id], backref="ventas_registradas")


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
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    fecha = db.Column(db.Date, default=date.today, nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # "venta" | "pago"
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(200))
    creado = db.Column(db.DateTime, default=ahora_argentina)
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id], backref="movimientos_cc_registrados")


class ProductoAlmacen(db.Model):
    """Producto y existencias del inventario del almacén."""
    __tablename__ = "productos_almacen"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=True)
    nombre = db.Column(db.String(150), nullable=False, index=True)
    categoria = db.Column(db.String(100))
    descripcion = db.Column(db.String(300))
    stock = db.Column(db.Numeric(12, 3), nullable=False, default=Decimal("0"))
    precio_costo = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    porcentaje_ganancia = db.Column(
        db.Numeric(6, 2), nullable=False, default=Decimal("0")
    )
    precio_venta = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado = db.Column(db.DateTime, nullable=False, default=ahora_argentina)

class ProductoVerduleria(db.Model):
    """Producto y existencias del inventario de verduleria."""
    __tablename__ = "productos_verduleria"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=True)
    nombre = db.Column(db.String(150), nullable=False, index=True)
    categoria = db.Column(db.String(100))
    descripcion = db.Column(db.String(300))
    stock = db.Column(db.Numeric(12, 3), nullable=False, default=Decimal("0"))
    precio_costo = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    porcentaje_ganancia = db.Column(
        db.Numeric(6, 2), nullable=False, default=Decimal("0")
    )
    precio_venta = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado = db.Column(db.DateTime, nullable=False, default=ahora_argentina)


    

class Proveedor(db.Model):
    """Proveedor al que se le compra mercadería."""
    __tablename__ = "proveedores"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    cuit = db.Column(db.String(20))
    telefono = db.Column(db.String(60))
    direccion = db.Column(db.String(200))
    email = db.Column(db.String(150))
    observaciones = db.Column(db.String(500))
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado = db.Column(db.DateTime, default=ahora_argentina)
    compras = db.relationship("CompraProveedor", backref="proveedor", lazy=True)


class CompraProveedor(db.Model):
    """Factura o compra y su deuda pendiente; cada pago se imputa aparte."""
    __tablename__ = "compras_proveedores"

    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    fecha = db.Column(db.Date, nullable=False, default=date.today, index=True)
    factura = db.Column(db.String(100))
    descripcion = db.Column(db.String(500))
    total = db.Column(db.Numeric(12, 2), nullable=False)
    forma_pago = db.Column(db.String(30), nullable=False)
    creado = db.Column(db.DateTime, nullable=False, default=ahora_argentina)
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])
    pagos = db.relationship("PagoCompraProveedor", backref="compra", lazy=True, cascade="all, delete-orphan")

    @property
    def pagado(self):
        return sum((p.monto for p in self.pagos), Decimal("0.00"))

    @property
    def saldo(self):
        return max(self.total - self.pagado, Decimal("0.00"))


class PagoCompraProveedor(db.Model):
    __tablename__ = "pagos_compras_proveedores"

    id = db.Column(db.Integer, primary_key=True)
    compra_id = db.Column(db.Integer, db.ForeignKey("compras_proveedores.id"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    fecha = db.Column(db.Date, nullable=False, default=date.today, index=True)
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    forma_pago = db.Column(db.String(30), nullable=False)
    observaciones = db.Column(db.String(300))
    creado = db.Column(db.DateTime, nullable=False, default=ahora_argentina)
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])


class Egreso(db.Model):
    __tablename__ = "egresos"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True, index=True)
    legacy_retiro_id = db.Column(db.Integer, db.ForeignKey("retiros_vendedor.id"), unique=True)
    legacy_pago_proveedor_id = db.Column(db.Integer, db.ForeignKey("pagos_proveedores.id"), unique=True)
    pago_compra_id = db.Column(db.Integer, db.ForeignKey("pagos_compras_proveedores.id"), unique=True)
    fecha = db.Column(db.DateTime, nullable=False, default=ahora_argentina, index=True)
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    concepto = db.Column(db.String(300), nullable=False)
    categoria = db.Column(db.String(30), nullable=False, default="gasto")
    forma_pago = db.Column(db.String(30), nullable=False, default="efectivo")
    observaciones = db.Column(db.String(500))
    estado = db.Column(db.String(20), nullable=False, default="activo")
    creado = db.Column(db.DateTime, nullable=False, default=ahora_argentina)
    modificado = db.Column(db.DateTime)
    modificado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id], backref="egresos_registrados")
    modificado_por = db.relationship("Usuario", foreign_keys=[modificado_por_id])
    auditorias = db.relationship("AuditoriaEgreso", backref="egreso", lazy=True, cascade="all, delete-orphan")
    pago_compra = db.relationship("PagoCompraProveedor", foreign_keys=[pago_compra_id])


class AuditoriaEgreso(db.Model):
    __tablename__ = "auditoria_egresos"

    id = db.Column(db.Integer, primary_key=True)
    egreso_id = db.Column(db.Integer, db.ForeignKey("egresos.id"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    fecha = db.Column(db.DateTime, nullable=False, default=ahora_argentina)
    anteriores = db.Column(db.JSON, nullable=False)
    nuevos = db.Column(db.JSON, nullable=False)
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])


class PagoProveedor(db.Model):
    """
    Egreso a un proveedor.
    tipo = "pago_total" | "pago_parcial"  -> sale plata de la caja
    tipo = "cuenta_corriente"             -> compra sin pagar, suma deuda
    """
    __tablename__ = "pagos_proveedores"

    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    fecha = db.Column(db.Date, default=date.today, nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(300))
    creado = db.Column(db.DateTime, default=ahora_argentina)
    proveedor = db.relationship("Proveedor", backref="pagos")
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])


class RetiroVendedor(db.Model):
    """Retiro de dinero de la caja hecho por el vendedor."""
    __tablename__ = "retiros_vendedor"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    fecha = db.Column(db.Date, default=date.today, nullable=False)
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(300))
    creado = db.Column(db.DateTime, default=ahora_argentina)
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])
