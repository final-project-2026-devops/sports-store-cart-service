import os

import aioboto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_TABLE_NAME = os.environ["DYNAMODB_TABLE_NAME"]

session = aioboto3.Session()


async def get_db_table():
    async with session.resource("dynamodb", region_name=AWS_REGION) as dynamodb:
        table = await dynamodb.Table(DYNAMODB_TABLE_NAME)
        yield table
