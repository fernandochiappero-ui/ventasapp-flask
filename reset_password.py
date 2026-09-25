# reset_password.py
#
# Recupera el acceso sin borrar clientes, ventas ni movimientos.
# Se ejecuta con: python reset_password.py

from getpass import getpass

from app import create_app
from extensions import db
from models import Usuario

app = create_app()

with app.app_context():
    usuarios = Usuario.query.order_by(Usuario.username).all()
    if not usuarios:
        print("No hay usuarios creados. Ejecutá init_db.py primero.")
        raise SystemExit(1)

    print("Usuarios disponibles:")
    for usuario in usuarios:
        print(f"- {usuario.username}")

    username = input("Usuario a recuperar: ").strip()
    usuario = Usuario.query.filter_by(username=username).first()
    if usuario is None:
        print("No existe un usuario con ese nombre.")
        raise SystemExit(1)

    password = getpass("Nueva contraseña: ").strip()
    while not password:
        password = getpass("La contraseña no puede estar vacía. Nueva contraseña: ").strip()

    confirmacion = getpass("Repetí la nueva contraseña: ").strip()
    if password != confirmacion:
        print("Las contraseñas no coinciden. No se modificó nada.")
        raise SystemExit(1)

    usuario.set_password(password)
    db.session.commit()
    print(f"Contraseña de '{username}' actualizada. Ya podés iniciar sesión.")
