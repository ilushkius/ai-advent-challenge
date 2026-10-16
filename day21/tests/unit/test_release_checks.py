"""Юнит-тесты проверок готовности релиза (день 35).

Проверки запускают подпроцессы ``pytest``, поэтому в тестах прогон подменяется:
проверяется РЕШЕНИЕ (пройдено/не пройдено, откуда взялся процент покрытия, что попало в
заметки и имена отказов), а не сам ``pytest``. Отдельно проверяется ``default_runner``
на несуществующей команде: отсутствие команды обязано приходить данными (код ``-1``), а
не исключением — отчёт должен быть и тогда, когда проверить не удалось.
"""
from backend.core import config
from backend.services import release_checks

#: Код возврата «команда не запустилась»: его же ставит ``default_runner``.
NOT_RUN = -1


def _runner(codes: dict, outputs: dict):
    """Подмена прогона команд: коды возврата и вывод по имени проверки.

    Имя проверки распознаётся по аргументам: у покрытия есть ``--cov``, у быстрого
    набора — нет. Ключи ``codes``/``outputs`` — ``"tests"`` и ``"coverage"``.
    """
    calls = []

    def run(argv, *, cwd, timeout):
        name = "coverage" if any(str(arg).startswith("--cov") for arg in argv) else "tests"
        calls.append({"name": name, "argv": list(argv), "cwd": cwd, "timeout": timeout})
        return codes.get(name, 0), outputs.get(name, ""), ""

    run.calls = calls
    return run


def test_run_checks_reports_passed_release():
    """Обе команды прошли, покрытие разобрано, файлы на месте — релиз готов."""
    outputs = {"tests": "1532 passed in 31.2s\n",
               "coverage": "TOTAL     24500   1800    93%\n"}
    result = release_checks.run_checks(runner=_runner({}, outputs),
                                       exists=lambda _rel: True)
    assert result["tests_passed"] is True
    assert result["coverage_percent"] == 93.0
    assert result["passed"] is True and result["notes"] == []
    assert [command["name"] for command in result["commands"]] == ["tests", "coverage"]
    assert result["commands"][0]["command"] == "uv run pytest -m not slow -q"
    assert result["files"]["readme"] == {"path": release_checks.FILES["readme"], "exists": True}


def test_run_checks_uses_day_directory_as_cwd():
    """Команды идут в папке дня: иначе ``uv run pytest`` не найдёт ``pytest.ini``."""
    runner = _runner({}, {})
    release_checks.run_checks(runner=runner, exists=lambda _rel: True)
    assert {call["cwd"] for call in runner.calls} == {config.MCP_FLEET_CWD}
    assert all(call["timeout"] == release_checks.release.CHECK_TIMEOUT for call in runner.calls)


def test_run_checks_collects_failed_names():
    """Проваленный набор тестов и пропавший README видны именами, а не только флагом."""
    outputs = {"tests": "3 failed, 1529 passed in 31.2s\n",
               "coverage": "TOTAL 1 1 99%\n"}
    result = release_checks.run_checks(runner=_runner({"tests": 1}, outputs),
                                       exists=lambda rel: rel != "README.md")
    assert result["tests_passed"] is False and result["passed"] is False
    assert result["readme_exists"] is False
    assert release_checks.failed_names(result) == ["tests", "README.md"]
    assert "3 failed" in result["commands"][0]["tail"]


def test_run_checks_notes_missing_coverage():
    """Неразобранный процент покрытия — заметка и ноль, а не исключение."""
    result = release_checks.run_checks(runner=_runner({}, {"tests": "ok\n"}),
                                       exists=lambda _rel: True)
    assert result["coverage_percent"] == 0.0
    assert result["notes"] == [release_checks.release.CHECKS_MISSING_METRICS]
    assert result["passed"] is True          # покрытие в решение о готовности не входит


def test_run_checks_never_raises_on_broken_commands():
    """Команда, которая не запустилась, — тоже результат (код -1 и текст причины)."""
    def broken(argv, *, cwd, timeout):
        return NOT_RUN, "", "команда не найдена: WinError 2"

    result = release_checks.run_checks(runner=broken, exists=lambda _rel: True)
    assert result["tests_passed"] is False
    assert result["commands"][0]["returncode"] == NOT_RUN
    assert "команда не найдена" in result["commands"][0]["tail"]


def test_coverage_percent_reads_last_number_of_total():
    """Процент берётся из строк ``TOTAL`` (последнее совпадение) и без них — ``None``."""
    assert release_checks.coverage_percent("TOTAL  100   5   95%\n") == 95.0
    assert release_checks.coverage_percent("TOTAL 1 2 77%\nTOTAL 3 4 88%\n") == 88.0
    assert release_checks.coverage_percent("no coverage here") is None
    assert release_checks.coverage_percent("") is None


def test_default_runner_reports_missing_command():
    """Отсутствующая команда приходит кодом ``-1`` и текстом, а не исключением."""
    code, out, err = release_checks.default_runner(
        ("definitely-not-a-command-day35", "--version"), cwd=config.MCP_FLEET_CWD,
        timeout=30.0)
    assert code == NOT_RUN and out == ""
    assert "не найдена" in err or "error" in err.lower()


def test_tail_keeps_only_last_characters():
    """В ответ уходит хвост вывода: ошибка ``pytest`` печатается в конце."""
    long_output = "x" * (release_checks.TAIL_CHARS * 2)
    result = release_checks.run_checks(runner=_runner({}, {"tests": long_output}),
                                       exists=lambda _rel: True)
    assert len(result["commands"][0]["tail"]) == release_checks.TAIL_CHARS
