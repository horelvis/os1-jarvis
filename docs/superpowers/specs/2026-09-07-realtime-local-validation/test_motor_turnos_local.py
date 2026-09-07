from __future__ import annotations

import asyncio
import unittest

from motor_turnos_local import Destination, LocalTurnEngine, TurnState


class MotorTurnosLocalTests(unittest.IsolatedAsyncioTestCase):
    async def aw(self, awaitable, timeout: float = 0.5):
        return await asyncio.wait_for(awaitable, timeout)

    async def start_accepted_turn(
        self,
        engine: LocalTurnEngine,
        *,
        persona: str = "papa",
        endpoint: str = "iphone-papa",
    ) -> tuple[str, str]:
        session = await self.aw(
            engine.open_session(persona, Destination("remote", endpoint))
        )
        await self.aw(engine.drain_available())
        turn = await self.aw(engine.start_turn(session))
        await self.aw(engine.drain_available())
        self.assertTrue(await self.aw(engine.accept_input(turn, "hola jarvis")))
        await self.aw(engine.drain_available())
        return session, turn

    async def collect_until(self, engine: LocalTurnEngine, count: int) -> list:
        events = []
        for _ in range(count):
            events.append(await self.aw(engine.get_event()))
        return events

    async def test_perdida_de_conexion_cancela_sin_redirigir_a_la_habitacion(self):
        engine = LocalTurnEngine(queue_size=8)
        session, turn = await self.start_accepted_turn(engine)

        await self.aw(engine.disconnect(session))
        late = await self.aw(engine.stream_text(turn, "secreto"))
        events = await self.aw(engine.drain_available())

        self.assertFalse(late)
        self.assertIn("response.cancelled", [event.type for event in events])
        self.assertNotIn(Destination("room"), [event.destination for event in events])
        cancelled = [event for event in events if event.type == "response.cancelled"]
        self.assertEqual(cancelled[0].destination, Destination("remote", "iphone-papa"))

    async def test_reconexion_misma_persona_otro_endpoint_no_roba_turno_viejo(self):
        engine = LocalTurnEngine(queue_size=16)
        old_session, old_turn = await self.start_accepted_turn(
            engine, persona="papa", endpoint="iphone-viejo"
        )
        await self.aw(engine.disconnect(old_session))
        new_session = await self.aw(
            engine.open_session("papa", Destination("remote", "iphone-nuevo"))
        )
        new_turn = await self.aw(engine.start_turn(new_session))
        self.assertTrue(
            await self.aw(engine.accept_input(new_turn, "segunda pregunta"))
        )

        self.assertFalse(await self.aw(engine.stream_text(old_turn, "respuesta vieja")))
        self.assertTrue(await self.aw(engine.stream_text(new_turn, "respuesta nueva")))
        self.assertTrue(await self.aw(engine.finish(new_turn)))
        events = await self.aw(engine.drain_available())

        fresh = [event for event in events if event.turn_id == new_turn]
        self.assertTrue(fresh)
        self.assertTrue(
            all(
                event.destination == Destination("remote", "iphone-nuevo")
                for event in fresh
            )
        )

    async def test_start_turn_bloqueado_no_crea_turno_tras_desconexion(self):
        engine = LocalTurnEngine(queue_size=1)
        session = await self.aw(
            engine.open_session("papa", Destination("remote", "iphone-papa"))
        )
        starter = asyncio.create_task(engine.start_turn(session))
        await asyncio.sleep(0)
        self.assertFalse(starter.done())

        disconnecting = asyncio.create_task(engine.disconnect(session))
        await asyncio.sleep(0)
        opened = await self.aw(engine.get_event())
        self.assertEqual(opened.type, "session.opened")

        with self.assertRaises(RuntimeError):
            await self.aw(starter)
        await self.aw(disconnecting)
        events = await self.aw(engine.drain_available())

        self.assertEqual([event.type for event in events], ["session.disconnected"])

    async def test_start_turn_concurrente_supersede_sin_dejar_turno_huerfano(self):
        engine = LocalTurnEngine(queue_size=1)
        session = await self.aw(
            engine.open_session("papa", Destination("remote", "iphone-papa"))
        )
        await self.aw(engine.drain_available())

        first_task = asyncio.create_task(engine.start_turn(session))
        second_task = asyncio.create_task(engine.start_turn(session))
        first_started = await self.aw(engine.get_event())
        self.assertEqual(first_started.type, "turn.started")
        first_turn = first_started.turn_id

        done, pending = await asyncio.wait(
            {first_task, second_task},
            timeout=0.2,
            return_when=asyncio.FIRST_COMPLETED,
        )
        self.assertEqual(len(done), 1)
        self.assertEqual(len(pending), 1)

        cancelled = await self.aw(engine.get_event())
        self.assertEqual(cancelled.type, "response.cancelled")
        self.assertEqual(cancelled.turn_id, first_turn)
        second_turn = await self.aw(next(iter(pending)))
        second_started = await self.aw(engine.get_event())

        self.assertEqual(second_started.type, "turn.started")
        self.assertEqual(second_started.turn_id, second_turn)
        self.assertEqual(
            await self.aw(engine.turn_state(first_turn)), TurnState.CANCELLED
        )
        self.assertEqual(
            await self.aw(engine.turn_state(second_turn)), TurnState.RECORDING
        )

    async def test_audio_bytes_fifo_bajo_saturacion_con_consumidor_concurrente(self):
        engine = LocalTurnEngine(queue_size=2)
        _session, turn = await self.start_accepted_turn(engine)
        chunks = [bytes([index]) for index in range(12)]
        seen: list[bytes] = []

        async def consumer():
            while len(seen) < len(chunks):
                event = await engine.get_event()
                if event.type == "response.audio":
                    seen.append(event.audio)

        consumer_task = asyncio.create_task(consumer())
        producer_results = await self.aw(
            asyncio.gather(*(engine.stream_audio(turn, chunk) for chunk in chunks))
        )
        await self.aw(consumer_task)

        self.assertTrue(all(producer_results))
        self.assertEqual(seen, chunks)

    async def test_texto_completo_fifo_bajo_saturacion_con_consumidor_concurrente(self):
        engine = LocalTurnEngine(queue_size=2)
        _session, turn = await self.start_accepted_turn(engine)
        texts = [f"frase completa {index}" for index in range(10)]
        seen: list[str] = []

        async def consumer():
            while len(seen) < len(texts):
                event = await engine.get_event()
                if event.type == "response.text":
                    seen.append(event.text)

        consumer_task = asyncio.create_task(consumer())
        for text in texts:
            self.assertTrue(await self.aw(engine.stream_text(turn, text)))
        await self.aw(consumer_task)

        self.assertEqual(seen, texts)

    async def test_terminal_exactamente_una_vez_con_finish_concurrente(self):
        engine = LocalTurnEngine(queue_size=8)
        _session, turn = await self.start_accepted_turn(engine)

        results = await self.aw(
            asyncio.gather(
                engine.finish(turn),
                engine.finish(turn),
                engine.error(turn, "late error"),
                engine.cancel(turn, "late cancel"),
            )
        )
        events = await self.aw(engine.drain_available())
        terminals = [
            event
            for event in events
            if event.type in {"response.done", "response.error", "response.cancelled"}
        ]

        self.assertEqual(results.count(True), 1)
        self.assertEqual(len(terminals), 1)
        self.assertEqual(await self.aw(engine.turn_state(turn)), TurnState.DONE)

    async def test_cancelacion_impide_publicar_productor_bloqueado(self):
        engine = LocalTurnEngine(queue_size=1)
        _session, turn = await self.start_accepted_turn(engine)
        self.assertTrue(await self.aw(engine.stream_text(turn, "ocupa la cola")))

        blocked = asyncio.create_task(engine.stream_audio(turn, b"late"))
        await asyncio.sleep(0)
        self.assertFalse(blocked.done())

        cancel_task = asyncio.create_task(engine.cancel(turn, "barge-in"))
        await asyncio.sleep(0)
        self.assertFalse(await self.aw(blocked))
        queued = await self.aw(engine.get_event())
        self.assertEqual(queued.type, "response.text")
        self.assertTrue(await self.aw(cancel_task))
        terminal = await self.aw(engine.get_event())
        self.assertEqual(terminal.type, "response.cancelled")

    async def test_productor_obsoleto_no_espera_detras_de_terminal_en_cola_llena(self):
        engine = LocalTurnEngine(queue_size=1)
        _session, turn = await self.start_accepted_turn(engine)
        self.assertTrue(await self.aw(engine.finish(turn)))

        self.assertFalse(
            await self.aw(engine.stream_audio(turn, b"late"), timeout=0.05)
        )
        self.assertEqual(await self.aw(engine.queued_count()), 1)
        terminal = await self.aw(engine.get_event())
        self.assertEqual(terminal.type, "response.done")

    async def test_error_por_transcripcion_vacia(self):
        engine = LocalTurnEngine(queue_size=8)
        session = await self.aw(
            engine.open_session("marta", Destination("remote", "iphone-marta"))
        )
        turn = await self.aw(engine.start_turn(session))
        await self.aw(engine.drain_available())

        self.assertFalse(await self.aw(engine.accept_input(turn, "   ")))
        event = await self.aw(engine.get_event())

        self.assertEqual(event.type, "response.error")
        self.assertEqual(event.reason, "empty transcription")
        self.assertEqual(event.destination, Destination("remote", "iphone-marta"))

    async def test_cancelacion_de_tarea_lenta_no_espera_a_que_haya_hueco_en_cola(self):
        engine = LocalTurnEngine(queue_size=1)
        _session, turn = await self.start_accepted_turn(engine)
        self.assertTrue(await self.aw(engine.stream_text(turn, "ocupa la cola")))

        slow_task = asyncio.create_task(asyncio.sleep(60))
        engine.attach_slow_task(turn, slow_task)
        cancel_task = asyncio.create_task(engine.cancel(turn, "timeout"))
        await asyncio.sleep(0)

        self.assertGreater(slow_task.cancelling(), 0)
        self.assertFalse(cancel_task.done())
        await self.aw(engine.get_event())
        self.assertTrue(await self.aw(cancel_task))

    async def test_cancel_descarta_solo_audio_pendiente_del_turno_cancelado_y_avisa(
        self,
    ):
        engine = LocalTurnEngine(queue_size=6)
        _session_a, turn_a = await self.start_accepted_turn(
            engine, persona="papa", endpoint="iphone-papa"
        )
        _session_b, turn_b = await self.start_accepted_turn(
            engine, persona="marta", endpoint="iphone-marta"
        )
        self.assertTrue(await self.aw(engine.stream_audio(turn_a, b"a1")))
        self.assertTrue(await self.aw(engine.stream_audio(turn_b, b"b1")))
        self.assertTrue(await self.aw(engine.stream_audio(turn_a, b"a2")))

        self.assertTrue(await self.aw(engine.cancel(turn_a, "barge-in")))
        events = await self.aw(engine.drain_available())

        self.assertNotIn(b"a1", [event.audio for event in events])
        self.assertNotIn(b"a2", [event.audio for event in events])
        self.assertIn(b"b1", [event.audio for event in events])
        notices = [
            event for event in events if event.type == "response.audio.discarded"
        ]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].count, 2)
        self.assertEqual(notices[0].turn_id, turn_a)

    async def test_terminal_cancelado_se_puede_recuperar(self):
        engine = LocalTurnEngine(queue_size=1)
        _session, turn = await self.start_accepted_turn(engine)
        self.assertTrue(await self.aw(engine.stream_text(turn, "ocupa la cola")))

        finishing = asyncio.create_task(engine.finish(turn))
        await asyncio.sleep(0)
        self.assertFalse(finishing.done())
        finishing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await finishing

        first = await self.aw(engine.get_event())
        self.assertEqual(first.type, "response.text")
        self.assertEqual(await self.aw(engine.recover_pending_terminals()), 1)
        terminal = await self.aw(engine.get_event())

        self.assertEqual(terminal.type, "response.done")
        self.assertEqual(await self.aw(engine.turn_state(turn)), TurnState.DONE)


if __name__ == "__main__":
    unittest.main()
