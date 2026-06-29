"""Stub for Angel One SmartAPI integration.
This wrapper contains baseline session, token, order, and quote methods.
"""
import asyncio
import httpx
from app.core.config import settings

class AngelOneClient:
    def __init__(self):
        self.api_key = settings.ANGEL_API_KEY
        self.client_id = settings.ANGEL_CLIENT_ID
        self.client_secret = settings.ANGEL_CLIENT_SECRET
        self.user_id = settings.ANGEL_USER_ID
        self.password = settings.ANGEL_PASSWORD
        self.pin = settings.ANGEL_2FA_PIN
        self.base = "https://api.angelone.in"
        self.session_token = None
        self.refresh_token = None
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

    async def login(self) -> dict:
        # Replace endpoint path with actual Angel One SmartAPI login flow.
        body = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'user_id': self.user_id,
            'password': self.password,
            'pin': self.pin,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f'{self.base}/v1/session/login', json=body, headers=self.headers)
            data = response.json()
            if response.status_code == 200:
                self.session_token = data.get('session_token')
                self.refresh_token = data.get('refresh_token')
                self.headers['Authorization'] = f'Bearer {self.session_token}'
            return data

    async def refresh_session(self) -> dict:
        if not self.refresh_token:
            return {'error': 'refresh token missing'}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f'{self.base}/v1/session/refresh',
                json={'refresh_token': self.refresh_token},
                headers=self.headers,
            )
            data = response.json()
            if response.status_code == 200:
                self.session_token = data.get('session_token')
                self.headers['Authorization'] = f'Bearer {self.session_token}'
            return data

    async def place_order(self, order_payload: dict) -> dict:
        await self.ensure_session()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f'{self.base}/v1/orders',
                json=order_payload,
                headers=self.headers,
            )
            data = response.json()
            if response.status_code >= 400:
                return {'status': 'failed', 'error': data}
            return data

    async def get_live_quote(self, symbol: str) -> dict:
        await self.ensure_session()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f'{self.base}/v1/market/quote/{symbol}',
                headers=self.headers,
            )
            data = response.json()
            if response.status_code >= 400:
                return {'error': data}
            return data

    async def get_account_status(self) -> dict:
        try:
            await self.ensure_session()
            return {
                'connected': True,
                'user_id': self.user_id,
                'client_id': self.client_id,
                'session_token': bool(self.session_token),
                'refresh_token': bool(self.refresh_token),
                'base_url': self.base,
            }
        except Exception as exc:
            return {'connected': False, 'error': str(exc)}

    async def ensure_session(self):
        if self.session_token is None:
            await self.login()

    def place_order_sync(self, order_payload: dict) -> dict:
        return asyncio.run(self.place_order(order_payload))

    def get_live_quote_sync(self, symbol: str) -> dict:
        return asyncio.run(self.get_live_quote(symbol))

    def get_account_status_sync(self) -> dict:
        return asyncio.run(self.get_account_status())
