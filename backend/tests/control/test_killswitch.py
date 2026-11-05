from sqlalchemy.orm import sessionmaker

from app.control.killswitch import KillSwitch


def switch(session):
    return KillSwitch(lambda: session)


def test_nothing_is_halted_by_default(session):
    assert switch(session).is_halted("paper_test") is False


def test_global_halt_halts_every_account(session):
    ks = switch(session)
    ks.halt("all", "market crash", "owner")
    assert ks.is_halted("paper_test") and ks.is_halted("zerodha_fno")


def test_account_halt_only_that_account(session):
    ks = switch(session)
    ks.halt("paper_test", "odd fills", "owner")
    assert ks.is_halted("paper_test") is True
    assert ks.is_halted("groww_equity") is False


def test_resume_clears_only_its_own_scope(session):
    ks = switch(session)
    ks.halt("all", "a", "owner")
    ks.halt("paper_test", "b", "owner")
    ks.resume("all", "owner")
    assert ks.is_halted("paper_test") is True  # the account halt is still on
    assert ks.is_halted("groww_equity") is False
    ks.resume("paper_test", "owner")
    assert ks.is_halted("paper_test") is False


def test_halt_persists_across_instances(engine):
    Session = sessionmaker(bind=engine)
    KillSwitch(Session).halt("all", "persist me", "owner")
    assert KillSwitch(Session).is_halted("anything") is True


def test_read_failure_counts_as_halted(session):
    def broken():
        raise RuntimeError("database down")

    assert KillSwitch(broken).is_halted("paper_test") is True


def test_a_broken_table_counts_as_halted(engine):
    Session = sessionmaker(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE control_flags")
    assert KillSwitch(Session).is_halted("paper_test") is True


def test_status_reports_scope_reason_and_who(session):
    ks = switch(session)
    ks.halt("paper_test", "odd fills", "pytest")
    ks.halt("all", "crash", "owner")
    status = ks.status()
    assert status["global"]["reason"] == "crash" and status["global"]["by"] == "owner"
    assert status["accounts"]["paper_test"]["reason"] == "odd fills"


def test_halting_twice_updates_the_reason(session):
    ks = switch(session)
    ks.halt("all", "first", "owner")
    ks.halt("all", "second", "owner")
    assert ks.status()["global"]["reason"] == "second"
