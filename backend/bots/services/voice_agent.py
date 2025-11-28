# import asyncio
# from agents.realtime import RealtimeAgent, RealtimeRunner

# async def main():
#     # 1) Определяем голосового агента
#     agent = RealtimeAgent(
#         name="Assistant",
#         instructions="Вы - голосовой ассистент. Отвечайте кратко и дружелюбно."
#     )

#     # 2) Настраиваем раннер: модель, голос, транскрипцию
#     runner = RealtimeRunner(
#         starting_agent=agent,
#         config={
#             "model_settings": {
#                 "model_name": "gpt-4o-realtime-preview",  # именно realtime-модель
#                 "voice": "alloy",                         # доступные: alloy, echo, onyx и др.
#                 "modalities": ["text", "audio"],
#                 "input_audio_transcription": {
#                     "model": "whisper-1"                  # STT через Whisper
#                 }
#             }
#         }
#     )

#     # 3) Запускаем сессию
#     session = await runner.run()
#     async with session:
#         # отправляем первый текст (можно и аудио)
#         await session.send_message("Здравствуйте! Чем могу помочь?")
#         # обрабатываем события: текстовые транскрипты и аудио-ответы
#         async for event in session:
#             if event.type == "conversation.item.response_audio_transcript":
#                 print(f"Assistant: {event.transcript}")
#             elif event.type == "conversation.item.input_audio_transcription":
#                 print(f"User: {event.transcript}")

# if __name__ == "__main__":
#     asyncio.run(main())
