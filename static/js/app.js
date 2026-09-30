function volverPantalla() {
  if (window.history.length > 1) {
    window.history.back();
    return;
  }
  window.location.href = "/";
}

document.addEventListener("DOMContentLoaded", () => {
  const avisoPago = document.getElementById("aviso-pago");
  if (avisoPago) {
    const claveUltimoPago = "ultimo-pago-notificado";

    const mostrarAvisoPago = (pago) => {
      avisoPago.textContent = `Pago recibido: ${pago.cliente} · $${pago.monto} · ${pago.fecha} ${pago.hora}`;
      avisoPago.hidden = false;
      window.setTimeout(() => {
        avisoPago.hidden = true;
      }, 9000);
    };

    const consultarPagos = (inicializar = false) => {
      const ultimoId = Number(localStorage.getItem(claveUltimoPago) || 0);
      const parametro = inicializar ? "&inicializar=1" : "";
      fetch(`/notificaciones/pagos?desde_id=${ultimoId}${parametro}`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      })
        .then((respuesta) => respuesta.ok ? respuesta.json() : null)
        .then((datos) => {
          if (!datos) return;
          if (inicializar) {
            localStorage.setItem(claveUltimoPago, String(datos.ultimo_id));
            return;
          }
          datos.pagos.forEach(mostrarAvisoPago);
          if (datos.ultimo_id > ultimoId) {
            localStorage.setItem(claveUltimoPago, String(datos.ultimo_id));
          }
        })
        .catch(() => {});
    };

    consultarPagos(true);
    window.setInterval(() => consultarPagos(false), 4000);
  }

  document.querySelectorAll(".menu-desplegable").forEach((menu) => {
    const boton = menu.querySelector(".menu-boton");
    if (!boton) return;

      boton.addEventListener("click", (evento) => {
      if (window.innerWidth <= 859) return; // en celular, el botón navega directo
      evento.preventDefault();
      const abierto = menu.classList.toggle("abierto");
      boton.setAttribute("aria-expanded", String(abierto));
    });

    document.addEventListener("click", (evento) => {
      if (!menu.contains(evento.target)) {
        menu.classList.remove("abierto");
        boton.setAttribute("aria-expanded", "false");
      }
    });
  });

  const modal = document.getElementById("confirmacion-modal");
  const mensaje = document.getElementById("confirmacion-mensaje");
  const cancelar = document.getElementById("confirmacion-cancelar");
  const aceptar = document.getElementById("confirmacion-aceptar");

  let formularioPendiente = null;

  if (modal && mensaje && cancelar && aceptar) {
    const cerrarModal = () => {
      modal.hidden = true;
      formularioPendiente = null;
    };

    document.querySelectorAll("form[data-confirmar-eliminacion]").forEach((formulario) => {
      formulario.addEventListener("submit", (evento) => {
        evento.preventDefault();
        formularioPendiente = formulario;
        mensaje.textContent = `¿Estás seguro de que querés eliminar al cliente ${formulario.dataset.cliente}? Sus ventas e historial se conservarán.`;
        modal.hidden = false;
        cancelar.focus();
      });
    });

    cancelar.addEventListener("click", cerrarModal);
    aceptar.addEventListener("click", () => {
      if (formularioPendiente) formularioPendiente.submit();
    });

    modal.addEventListener("click", (evento) => {
      if (evento.target === modal) cerrarModal();
    });

    document.addEventListener("keydown", (evento) => {
      if (evento.key === "Escape" && !modal.hidden) cerrarModal();
    });
  }

  const configurarAutocompletado = ({ campo, lista, alElegir }) => {
    if (!campo || !lista) return;

    const botones = [...lista.querySelectorAll(".sugerencia-cliente")];
    const crearCliente = lista.querySelector(".crear-cliente-sugerencia");
    const normalizar = (texto) => texto.trim().toLocaleLowerCase();
    let indiceSeleccionado = -1;

    const botonesVisibles = () => botones.filter((boton) => !boton.hidden);
    const actualizarSeleccion = (indice) => {
      const visibles = botonesVisibles();
      botones.forEach((boton) => boton.classList.remove("seleccionada"));
      if (!visibles.length) {
        indiceSeleccionado = -1;
        return;
      }
      indiceSeleccionado = (indice + visibles.length) % visibles.length;
      visibles[indiceSeleccionado].classList.add("seleccionada");
    };

    const elegirBoton = (boton) => {
      campo.value = boton.dataset.nombre;
      alElegir(boton);
      lista.hidden = true;
      indiceSeleccionado = -1;
    };

    const actualizarSugerencias = () => {
      const prefijo = normalizar(campo.value);
      indiceSeleccionado = -1;
      botones.forEach((boton) => boton.classList.remove("seleccionada"));
      if (!prefijo) {
        lista.hidden = true;
        return;
      }

      let cantidadVisibles = 0;
      botones.forEach((boton) => {
        const coincide = normalizar(boton.dataset.nombre).startsWith(prefijo);
        boton.hidden = !coincide;
        if (coincide) cantidadVisibles += 1;
      });
      lista.hidden = cantidadVisibles === 0 && !crearCliente;
      if (crearCliente) crearCliente.hidden = false;
    };

    campo.addEventListener("focus", actualizarSugerencias);
    campo.addEventListener("click", () => {
      if (campo.value) {
        campo.value = "";
        alElegir({ dataset: { id: "" } });
        actualizarSugerencias();
      }
    });
    campo.addEventListener("input", actualizarSugerencias);
    campo.addEventListener("keydown", (evento) => {
      if (evento.key === "Escape") {
        lista.hidden = true;
        indiceSeleccionado = -1;
        return;
      }
      if (lista.hidden || !botonesVisibles().length) return;
      if (evento.key === "ArrowDown") {
        evento.preventDefault();
        actualizarSeleccion(indiceSeleccionado + 1);
      } else if (evento.key === "ArrowUp") {
        evento.preventDefault();
        actualizarSeleccion(indiceSeleccionado - 1);
      } else if (evento.key === "Enter" && indiceSeleccionado >= 0) {
        evento.preventDefault();
        elegirBoton(botonesVisibles()[indiceSeleccionado]);
      }
    });
    botones.forEach((boton) => boton.addEventListener("click", () => elegirBoton(boton)));
    if (crearCliente) {
      crearCliente.addEventListener("click", () => {
        window.location.href = crearCliente.dataset.url;
      });
    }
    document.addEventListener("click", (evento) => {
      if (!lista.contains(evento.target) && evento.target !== campo) lista.hidden = true;
    });
  };

  configurarAutocompletado({
    campo: document.getElementById("buscar-cliente"),
    lista: document.getElementById("clientes-sugerencias"),
    alElegir: (boton) => {
      boton.closest("form").querySelector("input[name='q']").value = boton.dataset.nombre;
      boton.closest("form").submit();
    },
  });

  const campoVenta = document.getElementById("buscar-cliente-venta");
  const listaVenta = document.getElementById("clientes-sugerencias-venta");
  configurarAutocompletado({
    campo: campoVenta,
    lista: listaVenta,
    alElegir: (boton) => {
      document.getElementById("cliente_id").value = boton.dataset.id;
    },
  });

  configurarAutocompletado({
    campo: document.getElementById("buscar-cliente-pago"),
    lista: document.getElementById("clientes-sugerencias-pago"),
    alElegir: (boton) => {
      document.getElementById("cliente_id_pago").value = boton.dataset.id;
      const saldo = document.getElementById("saldo-cliente-pago");
      const detalle = document.getElementById("detalle-cliente-pago");
      if (saldo) {
        saldo.textContent = `Debe: $${boton.dataset.saldo}`;
        saldo.hidden = !boton.dataset.id;
      }
      if (detalle) {
        const movimientos = JSON.parse(boton.dataset.movimientos || "[]");
        detalle.innerHTML = movimientos.length
          ? `<strong>Detalle de cuenta</strong>${movimientos.map((movimiento) =>
              `<div class="detalle-movimiento"><span>${movimiento.tipo === "pago" ? "Pago" : "Venta"} · ${movimiento.fecha} ${movimiento.hora}</span><strong>$${movimiento.monto}</strong><small>${movimiento.descripcion}</small></div>`
            ).join("")}`
          : "<small>Sin movimientos registrados.</small>";
        detalle.hidden = !boton.dataset.id;
      }
    },
  });
});
  const botonMenuMovil = document.getElementById("menu-movil-boton");
  const menuPrincipal = document.getElementById("menu-principal");
  const botonCerrarMenu = document.getElementById("menu-movil-cerrar");

  if (botonMenuMovil && menuPrincipal) {
    const cerrarMenuMovil = () => {
      menuPrincipal.classList.remove("menu-abierto");
      botonMenuMovil.setAttribute("aria-expanded", "false");
    };

    botonMenuMovil.addEventListener("click", () => {
      const abierto = menuPrincipal.classList.toggle("menu-abierto");
      botonMenuMovil.setAttribute("aria-expanded", String(abierto));
    });

    if (botonCerrarMenu) {
      botonCerrarMenu.addEventListener("click", cerrarMenuMovil);
    }

    menuPrincipal.querySelectorAll("a").forEach((enlace) => {
      enlace.addEventListener("click", () => {
        if (!enlace.classList.contains("menu-boton")) cerrarMenuMovil();
      });
    });
  }