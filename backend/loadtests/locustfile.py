import json
import os
import uuid

from locust import HttpUser, between, task


class FinanceRagUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.headers = {"Content-Type": "application/json"}
        token = os.getenv("RAG_AUTH_TOKEN", "")
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

        fault_scenario = os.getenv("FAULT_SCENARIO", "")
        if fault_scenario:
            self.headers["X-Fault-Injection"] = fault_scenario

    @task(6)
    def query_non_stream(self):
        self.client.post(
            "/api/query",
            headers=self.headers,
            json={
                "query": "Compare Apple and Microsoft revenue growth drivers.",
                "top_k": 5,
                "stream": False,
            },
            name="/api/query non_stream",
        )

    @task(3)
    def query_sse(self):
        with self.client.post(
            "/api/query",
            headers=self.headers,
            json={
                "query": "Summarize recent Nvidia AI infrastructure demand signals.",
                "top_k": 5,
                "stream": True,
            },
            name="/api/query sse",
            stream=True,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status={response.status_code}")
                return
            event_count = 0
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith("data: "):
                    event_count += 1
                if event_count >= 3:
                    break
            if event_count == 0:
                response.failure("no_sse_events")

    @task(1)
    def deep_research_task(self):
        task_id = str(uuid.uuid4())
        payload = {
            "query": "Analyze the key risks in semiconductor supply chain concentration.",
            "output_format": "brief",
            "metadata": {"loadtest_task_id": task_id},
        }
        with self.client.post(
            "/api/research",
            headers=self.headers,
            data=json.dumps(payload),
            name="/api/research enqueue",
            catch_response=True,
        ) as response:
            if response.status_code not in {200, 201, 202}:
                response.failure(f"status={response.status_code}")
