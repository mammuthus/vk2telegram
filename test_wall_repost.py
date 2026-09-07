import asyncio
import unittest
from unittest.mock import patch

from bot import bot
from vk_messages import format_sender_header, format_wall_post, process_attachments


class WallRepostTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot.session.close())

    def run_async(self, coroutine):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coroutine)
        finally:
            loop.close()

    def test_regular_message_header(self):
        self.assertEqual(format_sender_header('Василиса <Гаврилова>'),
                         '<b>Василиса &lt;Гаврилова&gt;</b>:\n\n')

    def test_wall_post_text_uses_repost_header_and_escaped_body(self):
        wall = {'owner_id': -1, 'id': 2, 'text': 'Строка 1\nСтрока <2>'}
        self.assertEqual(format_sender_header('Василиса Гаврилова', True),
                         '<b>Василиса Гаврилова</b> (репост):\n\n')
        self.assertIn('Строка 1\nСтрока &lt;2&gt;', format_wall_post(wall))

    def test_wall_post_photo_uses_existing_attachment_pipeline(self):
        wall = {'owner_id': -1, 'id': 2, 'text': 'Текст', 'attachments': [{'type': 'photo', 'photo': {}}]}
        async def fake_process_attachment(*args):
            return {'type': 'photo', 'content': 'x'}
        with patch('vk_messages.process_attachment', new=fake_process_attachment):
            attachments = self.run_async(process_attachments([{'type': 'wall', 'wall': wall}]))
        self.assertEqual([attachment['type'] for attachment in attachments], ['text', 'photo'])
        self.assertIn('Текст', attachments[0]['content'])

    def test_empty_wall_uses_fallback(self):
        self.assertEqual(format_wall_post({'owner_id': -1, 'id': 2}), '📰 Запись на стене')

    def test_regular_photo_uses_existing_attachment_pipeline(self):
        async def fake_process_attachment(*args):
            return {'type': 'photo', 'content': 'x'}
        with patch('vk_messages.process_attachment', new=fake_process_attachment):
            attachments = self.run_async(process_attachments([{'type': 'photo', 'photo': {}}]))
        self.assertEqual(attachments, [{'type': 'photo', 'content': 'x'}])