bind = "0.0.0.0:" + __import__('os').getenv('PORT', '8000')
workers = int(__import__('os').getenv('GUNICORN_WORKERS', '3'))
worker_class = __import__('os').getenv('GUNICORN_WORKER_CLASS', 'sync')
timeout = int(__import__('os').getenv('GUNICORN_TIMEOUT', '120'))
accesslog = '-'
errorlog = '-'
