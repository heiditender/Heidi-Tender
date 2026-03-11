import dspy


class ExtractRequirementsSig(dspy.Signature):
    """你是投标包需求抽取专家，精通德语/英语/法语/中文。

    任务
    - 从投标包文件中识别每个投标产品，并抽取产品参数需求。
    - 投标包可能包含多个产品；每个产品都需要独立输出。

    输出要求
    - 只输出严格 JSON，不要 Markdown，不要解释性文字。
    - JSON 顶层结构固定为：
      {
        "tender_products": [...],
        "uncertainties": [...]
      }

    字段定义
    1) tender_products: 每个投标产品
    - product_key: 稳定标识（如 typ_01 / item_01）
    - product_name: 产品名称
    - quantity: 数量（可为 null）
    - requirements: 列表
      - field: 语义字段名（如 power_w, lumen, ip_rating, ugr, cri, cct, mounting）
      - operator: eq/gte/lte/gt/lt/between/in/contains/bool_true/bool_false
      - value: 数值或字符串
      - unit: 单位（可为 null）
      - is_hard: true 表示必须满足（按“硬/软约束判定规则”输出）
      - source: {file_name, snippet}

    2) uncertainties: 无法确定或缺失的信息列表

    规则
    - 允许使用外部知识仅用于理解投标包语义；输出字段名与值必须与投标包一致，不得新增需求。
    - 如果同一产品在多个表/页出现，合并需求参数。
    - 如果无法确定产品数量或名称，至少输出 1 个产品，并在 uncertainties 说明。

    硬/软约束判定规则（直接体现在 is_hard 字段）
    1) 若文本明确出现 MUST/SHALL/必需/必须/不可少/obligatorisch/zwingend/MUSS/KO/Mindestanforderung 等强制措辞 → is_hard=true
    2) 若文本出现 should/建议/推荐/idealerweise/soll 等偏好措辞 → is_hard=false
    3) 若无明确措辞，则按字段语义推断（只对数值字段）：
       - 硬约束（is_hard=true）：ip_rating, ik_rating, ugr, cri, ambient_temp_range, min_temp_c, max_temp_c
       - 软约束（is_hard=false）：power_w, lumen, cct, sdcm, life_hours, dimensions
    4) 若无法判断，一律设为 is_hard=false

    保证 JSON 语法正确。
    """

    tender_text = dspy.InputField(
        desc="Tender pack text (multi-language). Use it to extract product requirements."
    )
    web_context = dspy.InputField(
        desc="Optional web search context (Swiss lighting tenders/standards). Use only if relevant."
    )
    requirements_json = dspy.OutputField(
        desc=(
            "Strict JSON with tender_products and uncertainties. "
            "Each requirement includes field, operator, value, unit, is_hard, source."
        )
    )


class GenerateSQLSig(dspy.Signature):
    """你是一个 SQL 生成器，目标是从投标需求中生成只读查询 SQL（MySQL）。

    输入包含：
    - requirements: 投标需求 JSON（tender_products + requirements）
    - schema: 数据库表结构（tables -> columns）

    输出要求
    - 只输出严格 JSON，不要 Markdown，不要解释性文字。
    - JSON 顶层结构：
      {
        "queries": [
          {"product_key": "...", "sql": "SELECT ..."}
        ]
      }

    规则
    - 只允许 SELECT，不允许 DDL/DML，不允许子查询以外的多语句。
    - 只使用 schema 中出现的表和列。
    - 尽量使用 match_* 视图（match_products, match_specs, match_certs, match_assets）进行查询。
    - 若列中存在 is_current，请加上 is_current = 1 的过滤。
    - 每个投标产品输出一条 SQL。
    - 只考虑 is_hard=true 的需求写入 SQL，软约束一律不写入 SQL。
    - 先检查 schema：如果某个 is_hard=true 的需求在 schema 中没有对应字段，直接忽略该约束，不要编造字段。
    - SELECT 输出字段要覆盖 requirement 中出现的字段（硬约束 + 软约束都要尽量输出），用于后续匹配解释。
    - 若某个 requirement 字段在 schema 中没有对应列，则不要输出该列。

    数值方向（仅用于 is_hard=true）
    - ip_rating / ik_rating：数据库值应 >= 需求值
    - ugr：数据库值应 <= 需求值
    - cri：数据库值应 >= 需求值
    - ambient_temp_range / min_temp_c / max_temp_c：
      - 当需求为区间 [min, max] 时，数据库应满足 min_temp_c <= min 且 max_temp_c >= max

    SQL 结构建议
    - 优先使用 match_products mp JOIN match_specs ms ON mp.product_id = ms.product_id
    - 使用明确列名，如 ms.ugr, ms.cri, ms.ip_rating, ms.ik_rating, ms.min_temp_c, ms.max_temp_c
    - 如果没有任何硬约束可用，生成一个最宽松的查询（只加 is_current=1）

    保证 JSON 语法正确。
    """

    requirements_json = dspy.InputField(
        desc="JSON string of tender requirements (with is_hard flags)."
    )
    schema_json = dspy.InputField(
        desc="JSON string of schema metadata (tables/columns)."
    )
    web_context = dspy.InputField(
        desc="Optional web search context about lighting parameter norms or constraints."
    )
    sql_queries_json = dspy.OutputField(
        desc="Strict JSON: {\"queries\": [{\"product_key\": \"...\", \"sql\": \"SELECT ...\"}]}"
    )


class FormatMatchSig(dspy.Signature):
    """你是一个投标需求与数据库结果匹配的专家。

    输入包含：
    - requirements: 投标需求 JSON（tender_products + requirements）
    - schema: 数据库表结构（tables -> columns）
    - sql_results: 每个 product_key 的 SQL 查询结果（rows 列表）

    输出要求
    - 只输出严格 JSON，不要 Markdown，不要解释性文字。
    - JSON 顶层结构固定为：
      {
        "tender_products": [...],
        "match_results": [...],
        "uncertainties": [...]
      }

    字段定义
    1) tender_products: 直接复用输入中的投标产品

    2) match_results: 每个投标产品的匹配结果
    - product_key
    - candidates: [{
        db_product_id,
        db_product_name,
        passes_hard,
        matched_requirements,
        unmet_requirements,
        parameters: [{field, value, unit, db_field}]
      }]

    3) uncertainties: 无法确定或缺失的信息列表

    规则
    - 若某 product_key 的 rows 为空，则输出一个候选，passes_hard=false，并在 uncertainties 说明原因。
    - 若 rows 非空，从中选择最合适的 1 个候选产品（Top1）。
    - 允许使用外部知识仅用于理解语义；输出字段名与值必须与投标包/数据库输入一致，不得新增事实。
    - matched_requirements / unmet_requirements 允许为简短文本摘要。

    数值方向（用于匹配解释与同等条件下的排序；若 requirements 已给 operator，以 operator 为准）
    - lumen_output_max（光通量）：更高 => 更亮 => 更优
    - luminous_efficacy（lm/W）：更高 => 更高效 => 更优
    - electrical_power_w（功率）：一般更低更省电；若需求无 operator，默认“越低越好”
    - cri（显指）：更高 => 显色更好 => 更优
    - ugr（眩光）：更低 => 眩光更少 => 更优
    - ip_rating / ip_rating_two：更高 => 防护更强 => 更优（以满足最低要求为主）
    - ik_rating：更高 => 抗冲击更强 => 更优
    - runtime_hours（寿命小时）：更高 => 寿命更长 => 更优
    - color_temp_k_max（CCT）：不是性能优劣指标，按需求范围/最接近为优
    - min_temp_c / max_temp_c：能覆盖需求环境温度区间为优（min 更低、max 更高）

    保证 JSON 语法正确。
    """

    requirements_json = dspy.InputField(desc="JSON string of tender requirements.")
    schema_json = dspy.InputField(desc="JSON string of schema metadata.")
    sql_results_json = dspy.InputField(
        desc="JSON string of SQL results: list of {product_key, sql, rows}."
    )
    web_context = dspy.InputField(
        desc="Optional web search context on evaluation or compliance."
    )
    prompt_result_json = dspy.OutputField(
        desc="Strict JSON with tender_products, match_results, uncertainties."
    )


class ExtractRequirementsModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ExtractRequirementsSig)

    def forward(self, tender_text: str, web_context: str = ""):
        return self.predict(tender_text=tender_text, web_context=web_context)


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
