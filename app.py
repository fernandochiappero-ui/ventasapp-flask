# app.py
#
# Este es el "corazón" de la aplicación web. Un archivo Flask típico
# hace tres cosas:
#   1) Configura la app (base de datos, clave secreta, login).
#   2) Define "rutas": qué función de Python se ejecuta cuando el
#      navegador pide una URL determinada (ej: GET /clientes).
#   3) Cada función arma los datos y le pide a una plantilla HTML
#      (carpeta templates/) que los muestre.
#
# Para levantar el servidor: python app.py
# Luego abrir http://127.0.0.1:5000 en el navegador (PC o celular,
# ver README.md para cómo entrar desde el celular).

from datetime import date, datetime, timedelta
import os

from flask import Flask, jsonify, render_template, request, redirect, url_for, flash
from flask_login import (
    login_user, logout_user, login_required, current_user
)
from functools import wraps
from sqlalchemy import inspect, text
from extensions import db, login_manager
from models import Usuario, Cliente, Venta, MovimientoCC


def create_app():
    app = Flask(__name__)

    # SECRET_KEY: la usa Flask para firmar las "sesiones" (cookies que
    # recuerdan que el usuario ya inició sesión). En un proyecto real
    # esto NO se escribe a mano en el código: se lee de una variable
    # de entorno. Acá va un valor fijo para simplificar el aprendizaje.
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "cambia-esta-clave-por-una-propia"
    )

    # Le decimos a SQLAlchemy que use un archivo SQLite (una base de
    # datos liviana que es un solo archivo, ideal para un proyecto chico).
    database_url = os.environ.get("DATABASE_URL", "sqlite:///base_datos.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
        db.create_all()
        columnas_usuario = {
            columna["name"] for columna in inspect(db.engine).get_columns("usuarios")
        }
        if "rol" not in columnas_usuario:
            db.session.execute(
                text(
                    "ALTER TABLE usuarios ADD COLUMN rol "
                    "VARCHAR(20) NOT NULL DEFAULT 'administrador'"
                )
            )
            db.session.commit()
    login_manager.init_app(app)
    login_manager.login_view = "login"  # a dónde redirigir si no está logueado
    login_manager.login_message = "Iniciá sesión para continuar."

    def administrador_requerido(funcion):
        @wraps(funcion)
        @login_required
        def protegida(*args, **kwargs):
            if not current_user.es_administrador:
                flash("No tenés permiso para acceder a esa pantalla.", "error")
                return redirect(url_for("nueva_venta"))
            return funcion(*args, **kwargs)

        return protegida

    @login_manager.user_loader
    def load_user(user_id):
        # Flask-Login llama a esta función en cada request para saber
        # quién es el usuario logueado, a partir del id guardado en la cookie.
        return db.session.get(Usuario, int(user_id))

    # ------------------------------------------------------------------
    # LOGIN / LOGOUT
    # ------------------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            destino = "dashboard" if current_user.es_administrador else "nueva_venta"
            return redirect(url_for(destino))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            usuario = Usuario.query.filter_by(username=username).first()

            if usuario and usuario.check_password(password):
                login_user(usuario, remember=True)
                destino = "dashboard" if usuario.es_administrador else "nueva_venta"
                return redirect(url_for(destino))
            flash("Usuario o contraseña incorrectos.", "error")

        return render_template("login.html")

    @app.route("/cuenta", methods=["GET", "POST"])
    @administrador_requerido
    def configurar_cuenta():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password_actual = request.form.get("password_actual", "")
            password_nueva = request.form.get("password_nueva", "")
            password_confirmacion = request.form.get("password_confirmacion", "")

            if not username:
                flash("El nombre de usuario es obligatorio.", "error")
                return render_template("cuenta/configurar.html")

            otro_usuario = Usuario.query.filter(
                Usuario.username == username, Usuario.id != current_user.id
            ).first()
            if otro_usuario:
                flash("Ese nombre de usuario ya está en uso.", "error")
                return render_template("cuenta/configurar.html")

            quiere_cambiar_password = any(
                (password_actual, password_nueva, password_confirmacion)
            )
            if quiere_cambiar_password:
                if not current_user.check_password(password_actual):
                    flash("La contraseña actual es incorrecta.", "error")
                    return render_template("cuenta/configurar.html")
                if not password_nueva:
                    flash("La nueva contraseña no puede estar vacía.", "error")
                    return render_template("cuenta/configurar.html")
                if password_nueva != password_confirmacion:
                    flash("Las nuevas contraseñas no coinciden.", "error")
                    return render_template("cuenta/configurar.html")

                current_user.set_password(password_nueva)

            current_user.username = username
            db.session.commit()
            flash("Datos de acceso actualizados.", "success")
            return redirect(url_for("configurar_cuenta"))

        return render_template("cuenta/configurar.html")

    @app.route("/usuarios/nuevo", methods=["GET", "POST"])
    @administrador_requerido
    def nuevo_usuario():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            rol = request.form.get("rol", "vendedor")

            if not username or not password:
                flash("Usuario y contraseña son obligatorios.", "error")
                return render_template("usuarios/form.html")
            if rol not in ("administrador", "vendedor"):
                flash("Rol inválido.", "error")
                return render_template("usuarios/form.html")
            if Usuario.query.filter_by(username=username).first():
                flash("Ese nombre de usuario ya está en uso.", "error")
                return render_template("usuarios/form.html")

            usuario = Usuario(username=username, rol=rol)
            usuario.set_password(password)
            db.session.add(usuario)
            db.session.commit()
            flash(f"Usuario '{username}' creado como {rol}.", "success")
            return redirect(url_for("nuevo_usuario"))

        return render_template("usuarios/form.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/setup-inicial")
    def setup_inicial():
        clave = request.args.get("clave")
        if clave != os.environ.get("SETUP_SECRET", "cambiame123"):
            return "No autorizado", 403

        username = request.args.get("usuario")
        password = request.args.get("password")
        if not username or not password:
            return "Faltan parámetros: ?usuario=X&password=Y&clave=Z", 400

        usuario = Usuario.query.filter_by(username=username).first()
        if usuario is None:
            usuario = Usuario(username=username, rol="administrador")
            db.session.add(usuario)
        usuario.set_password(password)
        db.session.commit()

        return f"Usuario '{username}' creado/actualizado correctamente."

    # ------------------------------------------------------------------
    # DASHBOARD (resumen del día)
    # ------------------------------------------------------------------

    @app.route("/")
    @login_required
    def dashboard():
        hoy = date.today()
        ventas_hoy = Venta.query.filter_by(fecha=hoy).all()

        if current_user.es_vendedor:
            clientes = Cliente.query.filter_by(activo=True).all()
            deudas_actuales = sorted(
                [
                    {"cliente": cliente, "monto": cliente.saldo}
                    for cliente in clientes
                    if cliente.saldo > 0
                ],
                key=lambda deuda: deuda["cliente"].nombre.lower(),
            )
            return render_template(
                "dashboard_vendedor.html",
                hoy=hoy,
                ventas_hoy=ventas_hoy,
                total_hoy=round(sum(v.monto for v in ventas_hoy), 2),
                efectivo_hoy=round(
                    sum(v.monto for v in ventas_hoy if v.forma_pago == "efectivo"), 2
                ),
                cuenta_hoy=round(
                    sum(
                        v.monto
                        for v in ventas_hoy
                        if v.forma_pago == "cuenta_corriente"
                    ),
                    2,
                ),
                deudas_hoy=deudas_actuales,
                deuda_total_actual=round(
                    sum(deuda["monto"] for deuda in deudas_actuales), 2
                ),
            )

        total_hoy = round(sum(v.monto for v in ventas_hoy), 2)
        efectivo_hoy = round(
            sum(v.monto for v in ventas_hoy if v.forma_pago == "efectivo"), 2
        )
        cuenta_hoy = round(
            sum(v.monto for v in ventas_hoy if v.forma_pago == "cuenta_corriente"), 2
        )

        # Clientes con saldo pendiente (deuda), ordenados de mayor a menor
        clientes = Cliente.query.filter_by(activo=True).all()
        deudores = sorted(
            [c for c in clientes if c.saldo > 0],
            key=lambda c: c.saldo,
            reverse=True,
        )
        deuda_total = round(sum(c.saldo for c in deudores), 2)

        return render_template(
            "dashboard.html",
            hoy=hoy,
            ventas_hoy=ventas_hoy,
            total_hoy=total_hoy,
            efectivo_hoy=efectivo_hoy,
            cuenta_hoy=cuenta_hoy,
            deudores=deudores[:5],  # top 5 en el resumen
            deuda_total=deuda_total,
            cantidad_deudores=len(deudores),
        )

    # ------------------------------------------------------------------
    # CLIENTES
    # ------------------------------------------------------------------

    @app.route("/clientes")
    @administrador_requerido
    def listar_clientes():
        busqueda = request.args.get("q", "").strip()
        clientes_opciones = Cliente.query.filter_by(activo=True).order_by(
            Cliente.nombre
        ).all()
        clientes = []
        if busqueda:
            query = Cliente.query.filter_by(activo=True)
            query = query.filter(Cliente.nombre.ilike(f"%{busqueda}%"))
            clientes = query.order_by(Cliente.nombre).all()
        return render_template(
            "clientes/list.html",
            clientes=clientes,
            clientes_opciones=clientes_opciones,
            busqueda=busqueda,
        )

    @app.route("/clientes/nuevo", methods=["GET", "POST"])
    @login_required
    def nuevo_cliente():
        volver = request.args.get("volver") == "ventas" or request.form.get("volver") == "ventas"
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            telefono = request.form.get("telefono", "").strip()
            direccion = request.form.get("direccion", "").strip()
            notas = request.form.get("notas", "").strip()
            form_data = {
                "nombre": nombre,
                "telefono": telefono,
                "direccion": direccion,
                "notas": notas,
            }
            cliente = Cliente(
                nombre=nombre,
                telefono=telefono,
                direccion=direccion,
                notas=notas,
            )
            if not cliente.nombre:
                flash("El nombre es obligatorio.", "error")
                return render_template(
                    "clientes/form.html", cliente=None, form_data=form_data,
                    duplicados=[], volver=volver
                )

            nombre_normalizado = " ".join(nombre.casefold().split())
            duplicados = [
                existente
                for existente in Cliente.query.order_by(
                    Cliente.activo.desc(), Cliente.nombre
                ).all()
                if " ".join(existente.nombre.casefold().split()) == nombre_normalizado
            ]
            es_otro = request.form.get("es_otro") == "si"
            tiene_dato_diferenciador = any((telefono, direccion, notas))
            if duplicados and (
                not es_otro or not tiene_dato_diferenciador
            ):
                if es_otro and not tiene_dato_diferenciador:
                    flash(
                        "Para agregarlo como otro cliente, completá teléfono, "
                        "dirección o notas.",
                        "error",
                    )
                return render_template(
                    "clientes/form.html", cliente=None, form_data=form_data,
                    duplicados=duplicados, volver=volver
                )

            db.session.add(cliente)
            db.session.commit()
            flash(f"Cliente '{cliente.nombre}' cargado.", "success")
            if volver or current_user.es_vendedor:
                return redirect(url_for("nueva_venta", cliente_id=cliente.id))
            return redirect(url_for("listar_clientes"))

        return render_template(
            "clientes/form.html", cliente=None, form_data={}, duplicados=[], volver=volver
        )

    @app.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
    @administrador_requerido
    def editar_cliente(cliente_id):
        cliente = db.get_or_404(Cliente, cliente_id)

        if request.method == "POST":
            cliente.nombre = request.form.get("nombre", "").strip()
            cliente.telefono = request.form.get("telefono", "").strip()
            cliente.direccion = request.form.get("direccion", "").strip()
            cliente.notas = request.form.get("notas", "").strip()

            if not cliente.nombre:
                flash("El nombre es obligatorio.", "error")
                return render_template("clientes/form.html", cliente=cliente)

            db.session.commit()
            flash("Cliente actualizado.", "success")
            return redirect(url_for("listar_clientes"))

        return render_template("clientes/form.html", cliente=cliente)

    @app.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
    @administrador_requerido
    def eliminar_cliente(cliente_id):
        # No borramos de verdad (para no perder el historial de ventas):
        # lo marcamos como inactivo y dejamos de mostrarlo en las listas.
        cliente = db.get_or_404(Cliente, cliente_id)
        cliente.activo = False
        db.session.commit()
        flash(f"Cliente '{cliente.nombre}' dado de baja.", "success")
        return redirect(url_for("listar_clientes"))

    # ------------------------------------------------------------------
    # VENTAS
    # ------------------------------------------------------------------

    @app.route("/ventas")
    @administrador_requerido
    def listar_ventas():
        fecha_str = request.args.get("fecha", date.today().isoformat())
        try:
            fecha_filtro = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            fecha_filtro = date.today()

        ventas = (
            Venta.query.filter_by(fecha=fecha_filtro)
            .order_by(Venta.creado.desc())
            .all()
        )
        total = round(sum(v.monto for v in ventas), 2)
        return render_template(
            "ventas/list.html", ventas=ventas, fecha_filtro=fecha_filtro, total=total
        )

    @app.route("/ventas/nueva", methods=["GET", "POST"])
    @login_required
    def nueva_venta():
        clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
        cliente_seleccionado = None
        cliente_id_inicial = request.args.get("cliente_id", type=int)
        if cliente_id_inicial:
            cliente_seleccionado = Cliente.query.filter_by(
                id=cliente_id_inicial, activo=True
            ).first()

        if request.method == "POST":
            cliente_id = request.form.get("cliente_id", type=int)
            monto = request.form.get("monto", type=float)
            descripcion = request.form.get("descripcion", "").strip()
            forma_pago = request.form.get("forma_pago", "efectivo")
            if current_user.es_vendedor:
                fecha_venta = date.today()
            else:
                fecha_str = request.form.get("fecha") or date.today().isoformat()
                fecha_venta = datetime.strptime(fecha_str, "%Y-%m-%d").date()

            errores = []
            if not cliente_id:
                errores.append("Elegí un cliente.")
            elif not any(cliente.id == cliente_id for cliente in clientes):
                errores.append("Elegí un cliente activo de la lista.")
            if not monto or monto <= 0:
                errores.append("El monto tiene que ser mayor a 0.")
            if forma_pago not in ("efectivo", "cuenta_corriente"):
                errores.append("Forma de pago inválida.")

            if errores:
                for e in errores:
                    flash(e, "error")
                cliente_seleccionado = next(
                    (cliente for cliente in clientes if cliente.id == cliente_id),
                    None,
                )
                return render_template(
                    "ventas/form.html",
                    clientes=clientes,
                    cliente_seleccionado=cliente_seleccionado,
                    fecha_inicial=fecha_venta,
                )

            venta = Venta(
                cliente_id=cliente_id,
                fecha=fecha_venta,
                descripcion=descripcion,
                monto=monto,
                forma_pago=forma_pago,
            )
            db.session.add(venta)
            db.session.flush()  # así "venta" ya tiene un id antes del commit

            # Si la venta es a cuenta corriente, esto genera automáticamente
            # la deuda: un movimiento tipo "venta" que suma al saldo del cliente.
            if forma_pago == "cuenta_corriente":
                movimiento = MovimientoCC(
                    cliente_id=cliente_id,
                    venta_id=venta.id,
                    fecha=fecha_venta,
                    tipo="venta",
                    monto=monto,
                    descripcion=descripcion or "Venta a cuenta corriente",
                )
                db.session.add(movimiento)

            db.session.commit()
            flash("Venta registrada.", "success")
            if current_user.es_vendedor:
                return redirect(url_for("dashboard"))
            return redirect(url_for("listar_ventas", fecha=fecha_venta.isoformat()))

        return render_template(
            "ventas/form.html",
            clientes=clientes,
            cliente_seleccionado=cliente_seleccionado,
            fecha_inicial=date.today(),
        )

    # ------------------------------------------------------------------
    # CUENTA CORRIENTE
    # ------------------------------------------------------------------

    @app.route("/cuenta-corriente")
    @administrador_requerido
    def cuenta_corriente_index():
        clientes = Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
        clientes = sorted(clientes, key=lambda c: c.saldo, reverse=True)
        deuda_total = round(sum(cliente.saldo for cliente in clientes if cliente.saldo > 0), 2)
        return render_template(
            "cuenta/index.html", clientes=clientes, deuda_total=deuda_total
        )

    @app.route("/cuenta-corriente/<int:cliente_id>")
    @administrador_requerido
    def cuenta_corriente_detalle(cliente_id):
        cliente = db.get_or_404(Cliente, cliente_id)
        movimientos = sorted(cliente.movimientos, key=lambda m: (m.fecha, m.creado))

        # Armamos el saldo "corrido" (como en un resumen bancario), para
        # que se vea cómo fue subiendo o bajando la deuda con cada movimiento.
        saldo_corrido = 0.0
        filas = []
        for m in movimientos:
            saldo_corrido += m.monto if m.tipo == "venta" else -m.monto
            filas.append({"mov": m, "saldo": round(saldo_corrido, 2)})
        filas.reverse()  # mostramos lo más reciente primero

        return render_template("cuenta/detalle.html", cliente=cliente, filas=filas)

    @app.route("/cuenta-corriente/<int:cliente_id>/pago", methods=["POST"])
    @login_required
    def registrar_pago(cliente_id):
        cliente = db.get_or_404(Cliente, cliente_id)
        monto = request.form.get("monto", type=float)
        descripcion = request.form.get("descripcion", "").strip()
        if current_user.es_vendedor:
            fecha_pago = date.today()
        else:
            fecha_str = request.form.get("fecha") or date.today().isoformat()
            fecha_pago = datetime.strptime(fecha_str, "%Y-%m-%d").date()

        if not monto or monto <= 0:
            flash("El monto del pago tiene que ser mayor a 0.", "error")
            if current_user.es_vendedor:
                return redirect(url_for("registrar_pago_vendedor"))
            return redirect(url_for("cuenta_corriente_detalle", cliente_id=cliente_id))
        if current_user.es_vendedor and cliente.saldo <= 0:
            flash("El cliente no tiene deuda pendiente.", "error")
            return redirect(url_for("registrar_pago_vendedor"))
        if current_user.es_vendedor and monto > cliente.saldo:
            flash("El pago no puede superar la deuda pendiente.", "error")
            return redirect(url_for("registrar_pago_vendedor"))

        movimiento = MovimientoCC(
            cliente_id=cliente_id,
            fecha=fecha_pago,
            tipo="pago",
            monto=monto,
            descripcion=descripcion or "Pago / abono",
        )
        db.session.add(movimiento)
        db.session.commit()
        print(
            f"[PAGO] Usuario={current_user.username} Cliente={cliente.nombre} "
            f"Monto=${monto:,.2f} Fecha={fecha_pago.isoformat()}",
            flush=True,
        )
        flash(f"Pago de ${monto:,.2f} registrado.", "success")
        if current_user.es_vendedor:
            return redirect(url_for("dashboard"))
        return redirect(url_for("cuenta_corriente_detalle", cliente_id=cliente_id))

    @app.route("/pagos/nuevo", methods=["GET", "POST"])
    @login_required
    def registrar_pago_vendedor():
        clientes = [
            cliente
            for cliente in Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
            if cliente.saldo > 0
        ]
        movimientos_por_cliente = {
            cliente.id: [
                {
                    "tipo": movimiento.tipo,
                    "monto": f"{movimiento.monto:.2f}",
                    "fecha": movimiento.fecha.strftime("%d/%m/%Y"),
                    "hora": movimiento.creado.strftime("%H:%M"),
                    "descripcion": movimiento.descripcion or "Sin descripción",
                }
                for movimiento in sorted(
                    cliente.movimientos,
                    key=lambda movimiento: (movimiento.fecha, movimiento.creado),
                    reverse=True,
                )
            ]
            for cliente in clientes
        }

        if request.method == "POST":
            cliente_id = request.form.get("cliente_id", type=int)
            if not cliente_id or not any(cliente.id == cliente_id for cliente in clientes):
                flash("Elegí un cliente con deuda pendiente.", "error")
                return redirect(url_for("registrar_pago_vendedor"))
            return registrar_pago(cliente_id)

        return render_template(
            "pagos/form.html",
            clientes=clientes,
            fecha_inicial=date.today(),
            movimientos_por_cliente=movimientos_por_cliente,
        )

    @app.route("/notificaciones/pagos")
    @administrador_requerido
    def notificaciones_pagos():
        desde_id = request.args.get("desde_id", 0, type=int)
        inicializar = request.args.get("inicializar") == "1"
        ultimo_pago = MovimientoCC.query.filter_by(tipo="pago").order_by(
            MovimientoCC.id.desc()
        ).first()
        ultimo_id = ultimo_pago.id if ultimo_pago else 0

        if inicializar:
            return jsonify({"pagos": [], "ultimo_id": ultimo_id})

        pagos = (
            MovimientoCC.query.filter(
                MovimientoCC.tipo == "pago", MovimientoCC.id > desde_id
            )
            .order_by(MovimientoCC.id)
            .limit(20)
            .all()
        )
        return jsonify(
            {
                "pagos": [
                    {
                        "id": pago.id,
                        "cliente": pago.cliente.nombre,
                        "monto": f"{pago.monto:,.2f}",
                        "fecha": pago.fecha.strftime("%d/%m/%Y"),
                        "hora": pago.creado.strftime("%H:%M:%S"),
                        "descripcion": pago.descripcion or "Pago / abono",
                    }
                    for pago in pagos
                ],
                "ultimo_id": ultimo_id,
            }
        )

    @app.route("/notificaciones/pagos/lista")
    @administrador_requerido
    def lista_pagos_recibidos():
        pagos = (
            MovimientoCC.query.filter_by(tipo="pago")
            .order_by(MovimientoCC.creado.desc())
            .all()
        )
        return render_template("pagos/recibidos.html", pagos=pagos)

    @app.route("/deudores")
    @login_required
    def listar_deudores():
        deudores = [
            cliente
            for cliente in Cliente.query.filter_by(activo=True).order_by(Cliente.nombre).all()
            if cliente.saldo > 0
        ]
        return render_template(
            "pagos/deudores.html",
            deudores=deudores,
            deuda_total=round(sum(cliente.saldo for cliente in deudores), 2),
        )

    # ------------------------------------------------------------------
    # REPORTES
    # ------------------------------------------------------------------

    @app.route("/reportes")
    @administrador_requerido
    def reportes():
        hoy = date.today()
        desde_str = request.args.get("desde", (hoy - timedelta(days=7)).isoformat())
        hasta_str = request.args.get("hasta", hoy.isoformat())

        desde = datetime.strptime(desde_str, "%Y-%m-%d").date()
        hasta = datetime.strptime(hasta_str, "%Y-%m-%d").date()

        # --- Reporte de ventas en el rango ---
        ventas = (
            Venta.query.filter(Venta.fecha >= desde, Venta.fecha <= hasta)
            .order_by(Venta.fecha)
            .all()
        )
        total_ventas = round(sum(v.monto for v in ventas), 2)
        total_efectivo = round(
            sum(v.monto for v in ventas if v.forma_pago == "efectivo"), 2
        )
        total_cuenta = round(
            sum(v.monto for v in ventas if v.forma_pago == "cuenta_corriente"), 2
        )

        # Ventas agrupadas por día (para un mini-resumen día a día)
        ventas_por_dia = {}
        for v in ventas:
            ventas_por_dia.setdefault(v.fecha, []).append(v)
        resumen_diario = [
            {"fecha": f, "total": round(sum(v.monto for v in vs), 2), "cantidad": len(vs)}
            for f, vs in sorted(ventas_por_dia.items())
        ]

        # --- Reporte de deudas: movimientos de cuenta corriente en el rango ---
        movimientos = (
            MovimientoCC.query.filter(
                MovimientoCC.fecha >= desde, MovimientoCC.fecha <= hasta
            )
            .order_by(MovimientoCC.fecha)
            .all()
        )
        cargos = round(sum(m.monto for m in movimientos if m.tipo == "venta"), 2)
        pagos = round(sum(m.monto for m in movimientos if m.tipo == "pago"), 2)

        # Deuda total actual (a hoy, no depende del rango) por cliente
        clientes = Cliente.query.filter_by(activo=True).all()
        deudores = sorted(
            [c for c in clientes if c.saldo > 0], key=lambda c: c.saldo, reverse=True
        )
        deuda_total_actual = round(sum(c.saldo for c in deudores), 2)

        return render_template(
            "reportes/index.html",
            desde=desde,
            hasta=hasta,
            total_ventas=total_ventas,
            total_efectivo=total_efectivo,
            total_cuenta=total_cuenta,
            ventas=ventas,
            resumen_diario=resumen_diario,
            cargos=cargos,
            pagos=pagos,
            deudores=deudores,
            deuda_total_actual=deuda_total_actual,
        )

    return app


app = create_app()


if __name__ == "__main__":
    # host="0.0.0.0" es lo que permite entrar desde el celular (ver README.md).
    # debug=True reinicia el servidor solo cuando guardás un cambio de código
    # (muy útil mientras aprendés, pero se desactiva en producción real).
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
