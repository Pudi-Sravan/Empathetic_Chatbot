import redis

try:
    client = redis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True
    )

    print("Testing Redis connection...")

    if client.ping():
        print("Redis connection successful!")

except Exception as e:
    print("Redis connection failed:", e)