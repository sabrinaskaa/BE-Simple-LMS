from locust import HttpUser, between, task


class SimpleLmsUser(HttpUser):
    wait_time = between(1, 3)

    @task(5)
    def list_courses(self):
        self.client.get("/api/v1/courses?page=1&page_size=10", name="GET /courses")

    @task(3)
    def search_courses(self):
        self.client.get(
            "/api/v1/courses?search=python&ordering=-created_at&page=1&page_size=10",
            name="GET /courses search+sort+pagination",
        )

    @task(2)
    def popular_courses(self):
        self.client.get("/api/v1/analytics/popular-courses/?limit=10", name="GET /analytics/popular-courses")

    @task(1)
    def swagger_docs(self):
        self.client.get("/api/v1/docs", name="GET /api/v1/docs")
