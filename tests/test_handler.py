from src.lambda.handler import handler

def test_handler(monkeypatch):
    # mock out requests.get to use local file
    print(monkeypatch)