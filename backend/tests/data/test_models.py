"""The ORM models must import: init_db() imports them on every app start."""


def test_models_import_and_market_data_indexes_exist():
    from app.data.models import MarketData

    indexes = {index.name: [column.name for column in index.columns] for index in MarketData.__table__.indexes}
    assert indexes["idx_market_data_token_time"] == ["instrument_token", "timestamp"]
    assert indexes["idx_market_data_symbol_time"] == ["tradingsymbol", "timestamp"]
