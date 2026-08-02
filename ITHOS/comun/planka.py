#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente REST de PLANKA (v2.x). Sin dependencias externas (solo urllib). Auth por header
**X-API-Key** (en Planka 2.x el login email+password se deshabilita con SSO/OIDC).

Se usa para el tablero de TAREAS del equipo (por ahora solo el cliente ITHOS INTELLIHELP):
crear / mover / asignar / comentar tarjetas y leer el board, para avisar por WhatsApp y
mantener el Kanban al día. Verificado contra Planka 2.1.1. Ver la memoria del proyecto.
"""

import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger("planka")

TIPO_TARJETA = "project"          # Planka 2.x exige 'type' al crear (project = tarjeta normal)
POS_STEP = 65536                  # paso de posición estándar de Planka


class PlankaError(Exception):
    """Error de la API de Planka (incluye el código HTTP y el motivo que devuelve el server)."""


class Planka:
    def __init__(self, url, api_key):
        self.base = (url or "").rstrip("/")
        self.key = api_key

    def _req(self, path, method="GET", data=None, timeout=25):
        headers = {"Accept": "application/json", "X-API-Key": self.key}
        if data is not None:
            headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            cuerpo = ""
            try:
                cuerpo = e.read().decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                pass
            raise PlankaError(f"HTTP {e.code} en {method} {path} — {cuerpo[:200]}")

    # ------------------------------------------------------------------ lectura
    def proyectos(self):
        """Devuelve (items, included). included trae los 'boards' de todos los proyectos."""
        r = self._req("/api/projects")
        return r.get("items", []), r.get("included", {})

    def board(self, board_id):
        """included del board: 'lists', 'cards', 'cardMemberships', 'users', etc."""
        return self._req(f"/api/boards/{board_id}").get("included", {})

    def tarjeta(self, card_id):
        return self._req(f"/api/cards/{card_id}").get("item", {})

    def usuarios(self):
        return self._req("/api/users").get("items", [])

    # ------------------------------------------------------------------ tarjetas
    def crear_tarjeta(self, list_id, nombre, descripcion=None, position=POS_STEP):
        data = {"type": TIPO_TARJETA, "name": nombre, "position": position}
        if descripcion:
            data["description"] = descripcion
        return self._req(f"/api/lists/{list_id}/cards", "POST", data).get("item", {})

    def mover_tarjeta(self, card_id, list_id, position=POS_STEP):
        """Mueve la tarjeta a otra lista (Por hacer / Haciendo / En revisión / Hecho)."""
        return self._req(f"/api/cards/{card_id}", "PATCH",
                         {"listId": list_id, "position": position}).get("item", {})

    def mover_a_board(self, card_id, board_id, list_id, position=POS_STEP):
        """Mueve la tarjeta a OTRO board (a una lista de ese board). Conserva la MISMA tarjeta
        (id, asignados, comentarios). Se usa para 'arrastrar' lo no terminado al cambiar de
        semana/mes. Verificado contra Planka 2.1.1 (PATCH boardId+listId)."""
        return self._req(f"/api/cards/{card_id}", "PATCH",
                         {"boardId": board_id, "listId": list_id, "position": position}).get("item", {})

    def actualizar_tarjeta(self, card_id, **campos):
        return self._req(f"/api/cards/{card_id}", "PATCH", campos).get("item", {})

    def borrar_tarjeta(self, card_id):
        self._req(f"/api/cards/{card_id}", "DELETE")

    # ------------------------------------------------------------------ estructura (proyecto/board/lista)
    def crear_proyecto(self, nombre, tipo="private"):
        """Crea un proyecto nuevo (el dueño de la API key queda como manager). Devuelve su item."""
        return self._req("/api/projects", "POST", {"name": nombre, "type": tipo}).get("item", {})

    def crear_board(self, project_id, nombre, position=POS_STEP):
        """Crea un board dentro de un proyecto. Devuelve su item."""
        return self._req(f"/api/projects/{project_id}/boards", "POST",
                         {"name": nombre, "position": position}).get("item", {})

    def crear_lista(self, board_id, nombre, position=POS_STEP, tipo="active", color=None):
        """Crea una lista (columna) en un board. `color` es un nombre de la paleta de Planka
        (p. ej. 'berry-red'); sin color la columna queda gris. Devuelve su item."""
        datos = {"name": nombre, "position": position, "type": tipo}
        if color:
            datos["color"] = color
        return self._req(f"/api/boards/{board_id}/lists", "POST", datos).get("item", {})

    def actualizar_lista(self, list_id, **campos):
        """Cambia campos de una lista existente (nombre, color, posición)."""
        return self._req(f"/api/lists/{list_id}", "PATCH", campos).get("item", {})

    def borrar_board(self, board_id):
        self._req(f"/api/boards/{board_id}", "DELETE")

    def borrar_proyecto(self, project_id):
        """Borra un proyecto. Planka exige que NO tenga boards: primero se borran sus boards.
        (No lo usa el rollover —que conserva el historial— pero completa el cliente.)"""
        _items, inc = self.proyectos()
        for b in (inc.get("boards", []) if isinstance(inc, dict) else []):
            if str(b.get("projectId")) == str(project_id):
                try:
                    self.borrar_board(b["id"])
                except PlankaError:
                    pass
        self._req(f"/api/projects/{project_id}", "DELETE")

    # ------------------------------------------------------------------ asignación
    def asignar(self, card_id, user_id):
        """Asigna un usuario a la tarjeta. Idempotente: si ya estaba, NO es fatal (devuelve False)."""
        try:
            self._req(f"/api/cards/{card_id}/card-memberships", "POST", {"userId": str(user_id)})
            return True
        except PlankaError as e:
            log.debug("Planka: no pude asignar %s a la card %s: %s", user_id, card_id, e)
            return False

    def desasignar(self, card_id, user_id):
        try:
            self._req(f"/api/cards/{card_id}/card-memberships/userId:{user_id}", "DELETE")
            return True
        except PlankaError:
            return False

    # ------------------------------------------------------------------ comentarios
    def comentar(self, card_id, texto):
        """Agrega un comentario a la tarjeta (como el usuario de la API key = ITHOS)."""
        self._req(f"/api/cards/{card_id}/comments", "POST", {"text": texto})

    # ------------------------------------------------------------------ acceso (admin)
    def agregar_miembro_board(self, board_id, user_id, role="editor"):
        """Agrega un usuario como MIEMBRO del board. Es REQUISITO de Planka para poder asignarle
        tarjetas (asignar a alguien que no es miembro del board da 404 'User not found'). Igual que
        cuando se agrega a una persona a mano. Idempotente: si ya es miembro, no es fatal."""
        try:
            self._req(f"/api/boards/{board_id}/board-memberships", "POST",
                      {"userId": str(user_id), "role": role})
            return True
        except PlankaError:
            return False

    def asegurar_acceso(self, project_id, board_id, user_id):
        """El admin GLOBAL de Planka NO puede gestionar un proyecto/board ajeno hasta ser manager/
        miembro de ESE proyecto. ITHOS (admin) se auto-agrega. Idempotente (si ya está, se ignora)."""
        for path, payload in (
                (f"/api/projects/{project_id}/project-managers", {"userId": str(user_id)}),
                (f"/api/boards/{board_id}/board-memberships", {"userId": str(user_id), "role": "editor"})):
            try:
                self._req(path, "POST", payload)
            except PlankaError:
                pass


def desde_config(cfg):
    """Crea un Planka desde la sección 'planka' de la config del cliente:
    {"url": "...", "api_key": "...", ...}. None si no está configurado."""
    p = (cfg or {}).get("planka") or {}
    if not p.get("url") or not p.get("api_key"):
        return None
    return Planka(p["url"], p["api_key"])
