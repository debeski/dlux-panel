from asgiref.sync import async_to_sync, iscoroutinefunction, markcoroutinefunction, sync_to_async

from dlux.middleware import DluxMiddleware


class AgentApiBoundaryMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.async_mode = iscoroutinefunction(get_response)
        if self.async_mode:
            markcoroutinefunction(self)
            self.dlux_middleware = DluxMiddleware(async_to_sync(get_response))
        else:
            self.dlux_middleware = DluxMiddleware(get_response)

    @staticmethod
    def is_agent_api(request):
        return request.path.startswith("/api/agent/v1/")

    def __call__(self, request):
        if self.async_mode:
            return self.__acall__(request)
        if self.is_agent_api(request):
            return self.get_response(request)
        return self.dlux_middleware(request)

    async def __acall__(self, request):
        if self.is_agent_api(request):
            return await self.get_response(request)
        return await sync_to_async(self.dlux_middleware, thread_sensitive=True)(request)
