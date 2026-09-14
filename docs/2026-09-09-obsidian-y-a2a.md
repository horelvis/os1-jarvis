# Obsidian y A2A para coordinar las instancias

Estado: exploración realizada; propuesta, todavía no desplegada como canal entre
las dos sesiones existentes.

## Lo que existe en la caja

Servidor: `nexus@192.168.100.58`.

- Bóveda personal: `/home/nexus/boveda`.
- `OBSIDIAN_VAULT_PATH` está configurado con esa ruta en el entorno del proyecto.
- Contiene tres Markdown y siete PDF. No se encontró configuración `.obsidian`
  dentro de esa carpeta ni estructura de coordinación.
- Hermes incluye la skill `note-taking/obsidian`, basada en herramientas de
  archivos locales. No requiere un servidor Obsidian ni una API remota.
- La decisión de integración registrada el 2026-09-06 define la bóveda como
  material que Jarvis consulta, distinto de su memoria inyectada automáticamente.
  La escritura automática quedó aplazada; explorar no modifica esa decisión.
- El puente A2A ya está activo en `http://127.0.0.1:9910`.
  Su Agent Card se obtiene en `/.well-known/agent-card.json`.
  Implementa `message/send`, `message/stream`, `tasks/get` y `tasks/cancel`.
- El puente actual anuncia **Claude**, inicia trabajos y mantiene sus sesiones
  propias. Descubrir esa tarjeta no conecta automáticamente las dos instancias
  ya abiertas por el usuario.

## Recomendación

Usar como bóveda **del proyecto** la carpeta que ya contiene su documentación:

```text
/home/nexus/git/os1-jarvis/docs
```

La bóveda personal permanece como material del usuario. La del proyecto reúne
specs, planes, decisiones, informes y evidencias, sin duplicarlos en otra memoria.
Obsidian puede abrir esa carpeta existente; los agentes trabajan directamente
con sus Markdown por acceso local o SSH.

| Necesidad | Mecanismo |
|---|---|
| Enviar una tarea a otro agente | A2A `message/send` |
| Seguir avance o preguntas | A2A `message/stream` / estados de tarea |
| Consultar o cancelar trabajo | A2A `tasks/get` / `tasks/cancel` |
| Conservar análisis y pruebas | Markdown en la bóveda del proyecto |
| Consultar decisiones anteriores | Enlaces entre notas e índice del proyecto |
| Entregar un resultado duradero | Artefacto A2A que identifica el informe y su ruta |

No hace falta inventar una cola de mensajes SQLite dentro de `docs`. La
propuesta inicial de ese buzón se retiró antes de instalar nada en el servidor.

## Organización mínima propuesta

Dentro de `docs`, conservando las specs y planes existentes:

```text
COORDINACION.md              # índice y tarea activa; un único responsable
coordinacion/
  agentes.md                # endpoints/Agent Cards y responsabilidades
  tareas/
    <task-id>-ios.md         # informe de esta instancia
    <task-id>-backend.md     # informe de la otra instancia
  decisiones/
    <fecha>-<tema>.md        # conclusión con evidencia y enlaces
```

Cada agente escribe su propio informe; coordinar antes de modificar el mismo
archivo de código. El índice tiene un responsable explícito para no editarlo
a la vez. Las reservas de trabajo se comunican por A2A; una nota por sí sola
no bloquea un archivo.

Ejemplo de metadatos de una nota (rellenar con una tarea A2A real):

```yaml
---
task_id: <id-devuelto-por-A2A>
agent: backend
status: working
related_spec: ../../superpowers/plans/2026-09-08-hermes-authority-migration.md
---
```

El cuerpo debe separar: petición, evidencia, cambios, pruebas, resultado y
pendientes. No tratar la afirmación de un modelo como evidencia de ejecución.

## Alcance local

Mantener los documentos en la caja y acceder desde el Mac mediante SSH o una
sincronización entre equipos propios. No activar Obsidian Sync, iCloud ni
plugins que envíen las notas a un proveedor externo. No incluir credenciales,
audio de usuario o copias innecesarias de conversaciones en los informes.

## Pasos pendientes para ponerlo en marcha

1. Identificar cómo acceder a las dos sesiones activas y exponerlas mediante
   un adaptador A2A, o asignar explícitamente agentes servidos por el puente.
2. Publicar sus Agent Cards y verificar un intercambio dirigido con Task ID,
   recepción, respuesta y artefacto. Mantener servicios en loopback y usar SSH
   desde el Mac; no abrir otro puerto sin autenticación en la LAN.
3. Crear el índice de coordinación y acordar la propiedad de archivos/tareas.
4. Abrir `docs` como bóveda en Obsidian si el usuario quiere su interfaz visual.

Esta exploración no instaló plugins, no activó sincronización ni modificó las
notas personales. La ventaja inmediata es compartir contexto durable y legible;
el envío de mensajes entre sesiones sigue siendo trabajo del canal A2A.
