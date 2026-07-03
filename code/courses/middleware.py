class RateLimitHeaderMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        info = getattr(request, "_rate_limit_info", None)
        if info:
            response["X-RateLimit-Limit"] = str(info.get("limit", ""))
            response["X-RateLimit-Remaining"] = str(info.get("remaining", ""))
            response["X-RateLimit-Reset"] = str(info.get("reset", ""))
            if info.get("retry_after") is not None:
                response["Retry-After"] = str(info["retry_after"])
        return response
