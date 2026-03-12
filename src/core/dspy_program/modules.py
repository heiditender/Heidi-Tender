import dspy

from .signatures import (
    ExtractRequirementsSig,
    FormatMatchSig,
    GenerateSQLSig,
    ReviewHardnessSig,
)


class ExtractRequirementsModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ExtractRequirementsSig)

    def forward(
        self, tender_text: str, web_context: str = "", article_reference_context: str = ""
    ):
        return self.predict(
            tender_text=tender_text,
            web_context=web_context,
            article_reference_context=article_reference_context,
        )


class ReviewHardnessModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ReviewHardnessSig)

    def forward(self, tender_text: str, requirements_json: str, web_context: str = ""):
        return self.predict(
            tender_text=tender_text,
            requirements_json=requirements_json,
            web_context=web_context,
        )


class GenerateSQLModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(GenerateSQLSig)

    def forward(self, requirements_json: str, schema_json: str, web_context: str = ""):
        return self.predict(
            requirements_json=requirements_json, schema_json=schema_json, web_context=web_context
        )


class FormatMatchModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(FormatMatchSig)

    def forward(
        self, requirements_json: str, schema_json: str, sql_results_json: str, web_context: str = ""
    ):
        return self.predict(
            requirements_json=requirements_json,
            schema_json=schema_json,
            sql_results_json=sql_results_json,
            web_context=web_context,
        )
