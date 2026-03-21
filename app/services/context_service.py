from __future__ import annotations

from app.models.memory import RetrievalResult


class ContextService:
    @staticmethod
    def compose(results: list[RetrievalResult]) -> str:
        if not results:
            return "Relevant project memory:\n- No matching memory found."
        lines = ["Relevant project memory:"]
        for result in results:
            kind = "Fact" if result.item.type == "fact" else "Description"
            lines.append(f"- {kind}: {result.item.content}")
        return "\n".join(lines)
