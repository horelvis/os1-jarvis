# Enrolamiento: lo que tiene que cambiar en el widget

> **Para:** quien implemente el lado de la caja (`widget/jarvis_widget/`).
> **De:** el trabajo de la app nativa de iPhone, 2026-09-06.
> **Estado:** contrato acordado. El lado iOS se implementa contra esto.

Este documento es autocontenido: no hace falta leer el diseño de la app para
ejecutarlo. Si quieres el porqué de cada decisión está en
`docs/superpowers/specs/2026-09-06-bienvenida-y-emparejamiento-design.md`, en el
repo `ios-jarvis`.

## Contexto en un párrafo

La app de iPhone deja de tener pantalla de configuración. Un teléfono nuevo no
puede hacer nada hasta que se empareja escaneando el QR que muestra la caja, y de
ese QR sale **todo** lo que el teléfono necesita saber: dónde está la caja, quién
es él, y qué certificado debe exigirle. Hoy el QR lleva solo el token, así que la
dirección y el certificado viven dentro de la app — y eso obliga a recompilar y
reinstalar cuatro teléfonos cada vez que cambia cualquiera de las dos cosas.

## Cambio 1 — el QR lleva un sobre, no un token

**Hoy:** el QR contiene el token de enrolamiento.

**A partir de ahora:** contiene este JSON.

```json
{
  "v": 1,
  "url": "wss://brain.local:8765/ws",
  "token": "…",
  "ca": "sha256/BASE64_DEL_HASH_SPKI"
}
```

| Campo | Regla |
|---|---|
| `v` | Entero. Versión del formato. Hoy `1` |
| `url` | La WSS que ya sirve `remote.py`. **Esquema `wss` obligatorio** |
| `token` | El mismo token de enrolamiento que ya se genera hoy |
| `ca` | Huella SHA-256 de la **clave pública** de la CA de la casa, en formato HPKP |

Los cuatro son obligatorios. La app rechaza el sobre entero si falta cualquiera,
si la versión no la reconoce, o si la URL no es `wss`. No hay valores por
defecto: un sobre incompleto no cae a la validación del sistema, se rechaza.

### Cómo calcular `ca`

```sh
echo "sha256/$(
  openssl x509 -in ca.crt -pubkey -noout \
    | openssl pkey -pubin -outform der \
    | openssl dgst -sha256 -binary \
    | openssl base64
)"
```

**Importante: es el hash de la clave pública, no del certificado.** Es
deliberado. Si mañana renuevas el certificado de la caja conservando la misma
clave, los teléfonos siguen conectando sin tocar nada. Si se fijara el
certificado, ese día los cuatro dejarían de funcionar a la vez y habría que
reenrolarlos todos.

La contrapartida: si **rotas la clave** de la CA, hay que reenrolar todos los
teléfonos. Tenlo presente antes de rotarla.

### Efecto secundario bueno

La trampa operativa que ya estaba registrada —*si la IP de la caja cambia por
DHCP hay que reenrolar los teléfonos*— deja de implicar recompilar. Con la URL
dentro del QR, reenrolar arregla también la dirección.

## Cambio 2 — la aceptación devuelve el nombre de la persona

Cuando la caja acepta un enrolamiento, debe devolver al teléfono el nombre de la
persona a la que acaba de asociarlo.

```json
{ "type": "enrolled", "name": "Nata" }
```

**Para qué:** la app termina el emparejamiento diciendo *«este teléfono es el de
Nata»*. Sin eso, quien empareja cuatro teléfonos seguidos no tiene forma de saber
si ha enrolado el que creía. Es la única confirmación posible.

**No cambia nada de la regla de identidad.** La app *muestra* lo que la caja le
dice; no lo afirma ni lo guarda como algo que pueda invocar después. Sigue sin
enviar nunca un nombre ni un `user_id`: solo su token, y la caja sigue siendo
quien mapea token → persona → `chat_id`.

**Ajústalo al flujo que exista.** No sé si el enrolamiento actual se resuelve por
HTTP o dentro del propio socket. El requisito es *que la respuesta de aceptación
incluya el nombre*; la forma exacta la decides tú según lo que ya haya. Si acabas
usando otra cosa distinta a `{"type":"enrolled","name":…}`, dilo y ajustamos el
lado iOS.

Si este cambio no llegara a hacerse, el emparejamiento funciona igual y termina
sin nombre. Es peor, pero no bloquea.

## Lo que va a hacer la app, para que puedas probarlo

Con esto puedes verificar el lado de la caja sin tener un iPhone delante:

1. **Exige la huella.** Conecta a la `url` del sobre validando la cadena contra
   la CA cuya clave pública tenga esa huella, y **solo** esa. Si el certificado
   que presenta la caja no encaja, **cancela el emparejamiento y lo dice**. No
   hay «continuar de todos modos».
2. **Rechaza `ws://`.** Un QR con TLS desactivado se descarta antes de conectar.
3. **Rechaza sobres incompletos** o de versión desconocida, diciendo cuál de las
   dos cosas es.
4. **Presenta el token** tal y como lo hace hoy la página.
5. Si más adelante la caja **rechaza el token** —revocado, o la IP cambió—, la
   app vuelve a la pantalla de emparejamiento explicando qué pasó, en lugar de
   reintentar en silencio.

Un `openssl s_client` contra la caja con la CA correcta, y otro con una CA
distinta, cubren los casos 1 y 2 sin salir del Mac.

## Lo que NO debe cambiar

- **La app nunca manda un nombre ni un `user_id`.** Si pudiera afirmar una
  identidad, el móvil de una hija podría pedir el perfil del padre, que tiene
  `terminal`. Toda la frontera de la spec de identidad se apoya en que el token
  es lo único que el teléfono puede decir de sí mismo.
- **El `nameConstraints` de la CA** sigue limitado a `brain.local` y la LAN. La
  app cuenta con ello: cuando no consigue conectar, el mensaje que enseña es
  *«¿estás en la wifi de casa?»*, porque esa es la causa real casi siempre.
- **`movil.html` no se toca.** Sigue siendo el respaldo para un teléfono sin app.

## Fuera de alcance

- **Desenrolar empujando desde la caja.** El teléfono se entera cuando su token
  deja de ser aceptado, y con eso basta.
- **Cualquier cosa relacionada con la cámara del teléfono más allá de leer este
  QR.** El uso de la cámara se autorizó solo para el emparejamiento; la imagen no
  sale del teléfono ni se guarda, y `jarvis_vision` no se toca.
