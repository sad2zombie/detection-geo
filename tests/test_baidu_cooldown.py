# -*- coding: utf-8 -*-
import time

from core.web_engines import baidu as baidu_engine


def test_baidu_cooldown_public_api(monkeypatch):
    baidu_engine._baidu_blocked_until = 0.0
    assert baidu_engine.is_in_cooldown() is False
    assert baidu_engine.cooldown_remaining_seconds() == 0

    baidu_engine._baidu_blocked_until = time.time() + 30
    assert baidu_engine.is_in_cooldown() is True
    assert 0 < baidu_engine.cooldown_remaining_seconds() <= 30

    baidu_engine._baidu_blocked_until = 0.0
