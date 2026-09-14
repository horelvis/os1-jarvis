# Legacy phone transcription: local Whisper only

Date: 2026-09-09. Implemented in widget and ios-jarvis.

The user clarified that audio/transcription must not leave the house. The iOS
client removes Apple Speech rather than allowing an external recognition fallback.

The paired `/ws` endpoint gains one server event, before dispatch to Hermes:

```json
{"type":"transcript","text":"El perfil que estoy buscando es de Alfresco."}
```

The value is precisely `spoken`, also passed to `client.send_chat`. It is local
Whisper's processed transcription, not a second recognition. Delivery uses the
original admitted `PhoneOutput`; closed/private destinations reject late output.
It never broadcasts to the room or another connection of the same persona.
Existing `text` frames remain assistant responses. Authentication, certificate
pinning, input PCM and `start`/`end`/`interrupt` remain unchanged. Older native
clients ignore this event. No identity fields are supplied by the phone.

This extends the legacy endpoint; it does not implement the `/voice/local`
hello/ready handshake or claim that all Hermes tools are network-isolated.

Verification: 790 widget tests and 157 iOS Simulator tests pass. The dispatch
regression executes the real callback with synthetic PCM/STT and compares the
exact text delivered to the phone with that dispatched to Hermes. The signed
iOS binary no longer links Speech.framework or requests speech-recognition
permission. Physical phone confirmation remains pending.
