import dspy


class ExtractRequirementsSig(dspy.Signature):
    """你是瑞士照明行业投标需求抽取专家，精通德语/英语/法语/中文。

    任务
    - 从投标包文件中识别每个投标产品，并抽取尽可能全面的需求信息，供后续 SQL 生成与匹配解释使用。
    - 投标包可能包含多个产品；每个产品都需要独立输出。
    - 除基础技术参数外，也要尽量抽取：安装方式、控制方式、认证/标准、环境条件、材质颜色、尺寸、
      品牌/型号/货号、交付/验收/保修/服务/文档等（只要原文出现且能结构化）。
    - 输入里会提供 article_reference_context（来自 articles_single_record/articles_multi_records）：
      - 仅用于熟悉常见参数术语，以及在语义不清时辅助判断数值方向（gte/lte/between）与容忍度。
      - 若与投标包原文冲突，始终以投标包原文为准。

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
      - operator: 必须是标准枚举之一：eq/gte/lte/gt/lt/between/in/contains/bool_true/bool_false
      - value: 数值或字符串
      - unit: 单位（可为 null）
      - source: {file_name, snippet}

    2) uncertainties: 无法确定或缺失的信息列表

    规则
    - 允许使用外部知识仅用于理解投标包语义；输出字段名与值必须与投标包一致，不得新增需求。
    - 如果同一产品在多个表/页出现，合并需求参数。
    - 如果无法确定产品数量或名称，至少输出 1 个产品，并在 uncertainties 说明。
    - source.snippet 必须来自投标包原文，不得引用 article_reference_context 文本。
    - 本阶段只负责“需求抽取与 operator 归一化”，不要输出 is_hard；硬/软约束由下游独立阶段判定。
    - 若出现占位符/空值（如 "-", ".", "n/a", "leer"），不要输出空 requirement；应在 uncertainties 说明缺失。

    operator 判定规则（重点）
    1) 若文本有明确比较符号或措辞（>=, <=, >, <, at least, at most, mindestens, maximal, 不低于, 不高于等），
       必须映射为标准 operator（gte/lte/gt/lt），禁止输出自然语言 operator。
    2) 若文本是“最低要求/Min requirement/Mindestanforderung”但方向未显式给出，可结合参数语义与 article_reference_context 推断：
       - 对“越大越好/门槛下限”参数用 gte（如光通量、光效、CRI、IP/IK、寿命等）。
       - 对“越小越好/门槛上限”参数用 lte（如UGR、功率上限、B值、MacAdam等）。
    3) 若上下文体现容忍度（如 tolerance 5%、±100），优先用 between 表达区间。
    4) 若仍不确定方向，保守使用 eq，并在 uncertainties 说明原因。
    5) 数值规范化：
       - 能提取数值时，value 优先输出数值而非混合文本（例如 "Ra > 80" -> operator=gte, value=80）。
       - IP/IK 等等级尽量提取数值部分（例如 "IP 20" -> value=20，unit="IP"）。
       - 区间统一为 between + [min, max]（例如 "-10°C bis +35°C" -> [-10, 35]）。

    保证 JSON 语法正确。
    """

    tender_text = dspy.InputField(
        desc="Tender pack text (multi-language). Use it to extract product requirements."
    )
    web_context = dspy.InputField(
        desc="Optional web search context (Swiss lighting tenders/standards). Use only if relevant."
    )
    article_reference_context = dspy.InputField(
        desc=(
            "Reference extracted from articles_single_record/articles_multi_records: "
            "common field terminology + comment-based operator/tolerance hints."
        )
    )
    requirements_json = dspy.OutputField(
        desc=(
            "Strict JSON with tender_products and uncertainties. "
            "Each requirement includes field, operator, value, unit, source. "
            "Do not include is_hard in extraction stage output."
        )
    )


class ReviewHardnessSig(dspy.Signature):
    """你是一个投标约束判定专家，专门复核每条 requirement 的硬/软属性。

    输入包含：
    - tender_text: 投标原文
    - requirements_json: 已抽取出的 requirements 结构（不含 is_hard）

    输出要求
    - 只输出严格 JSON，不要 Markdown，不要解释性文字。
    - 输出结构固定为：
      {
        "product_reviews": [
          {
            "product_key": "...",
            "decisions": [
              {"requirement_index": 0, "is_hard": true, "confidence": 0.93}
            ]
          }
        ],
        "uncertainties": [...]
      }
    - requirement_index 必须对应 requirements_json 中同一 product_key 下 requirements 列表的 0-based 下标。
    - confidence 范围 [0,1]。
    - 本阶段只输出复核决策，不要回写完整 requirements_json。

    判定原则（不要按字段名硬编码）
    1) 若原文有强制词（MUST/SHALL/必须/最低门槛/KO/Ausschlusskriterium 等）=> is_hard=true
    2) 若原文有偏好词（should/optional/建议/推荐/bonus/soll 等）=> is_hard=false
    3) 若上下文是“合格门槛/技术必达/验收必达”=> is_hard=true
    4) 若上下文是“评分项/优化项/参考值”=> is_hard=false
    5) 不确定时设为 false，并在 uncertainties 写明歧义来源

    约束
    - 同一字段在不同产品可不同，不得按字段名一刀切。
    - 保持 JSON 语法正确。
    """

    tender_text = dspy.InputField(desc="Original tender text.")
    requirements_json = dspy.InputField(
        desc="Extracted requirements JSON (without is_hard). Review per requirement index."
    )
    web_context = dspy.InputField(desc="Optional context.")
    reviewed_hardness_json = dspy.OutputField(
        desc=(
            "Strict JSON: {product_reviews:[{product_key, decisions:[{requirement_index,is_hard,confidence}]}], "
            "uncertainties:[...]}"
        )
    )


class AlignRequirementsToSchemaSig(dspy.Signature):
    """你是投标需求字段标准化专家，负责把招标文本里的多样字段名对齐到数据库可查询字段语义。

    输入包含：
    - requirements_json: 已抽取并复核过 is_hard 的需求 JSON
    - schema_json: 数据库 schema（tables -> columns）
    - article_reference_context: 术语参考（可选）
    - web_context: 外部背景（可选）

    输出要求
    - 只输出严格 JSON，不要 Markdown，不要解释性文字。
    - 输出结构必须与 requirements_json 相同：
      {
        "tender_products": [...],
        "uncertainties": [...]
      }
    - 仅允许调整 requirement.field（必要时可规范 unit 文本）；不要改 operator/value/is_hard/source。

    对齐目标（优先映射到这些标准字段名）
    - manufacturer
    - model / model_name
    - article_number
    - power_w
    - lumen / lumen_lm
    - cct / cct_k
    - cri
    - ugr
    - runtime_hours / life_hours / lifetime_h
    - ip_rating
    - ik_rating
    - ambient_temp_range / ambient_temperature
    - control

    规则
    1) 结合 schema 中真实列名语义进行映射（如 electrical_power_w -> power_w，color_temp_k_max -> cct_k）。
    2) 字段名可多语言/缩写/品牌术语，需语义归一；禁止按字面硬匹配。
    3) 若无法高置信映射，保留原 field，不要臆造；在 uncertainties 写明原因。
    4) 同一含义字段在不同产品中尽量统一命名。
    5) 保持 JSON 语法正确。
    """

    requirements_json = dspy.InputField(desc="Reviewed requirements JSON.")
    schema_json = dspy.InputField(desc="Database schema JSON.")
    article_reference_context = dspy.InputField(desc="Optional article-based terminology hints.")
    web_context = dspy.InputField(desc="Optional web/file-search context.")
    aligned_requirements_json = dspy.OutputField(
        desc="Strict JSON with the same structure as requirements_json, field names aligned to schema semantics."
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
    - 严格以 requirements 中的 operator 与 is_hard 为准，不要重新推断数值方向或软硬约束。
    - 只考虑 is_hard=true 的需求写入 SQL；软约束仅用于 SELECT 输出字段与后续解释，不进 WHERE。
    - 先检查 schema：如果某个 is_hard=true 的需求在 schema 中没有对应字段，直接忽略该约束，不要编造字段。
    - SELECT 输出字段要覆盖 requirement 中出现的字段（硬约束 + 软约束都要尽量输出），用于后续匹配解释。
    - 若某个 requirement 字段在 schema 中没有对应列，则不要输出该列。
    - operator 到 SQL 的映射应与 requirements 保持一致：
      - eq -> =, gte -> >=, lte -> <=, gt -> >, lt -> <
      - between -> BETWEEN / 区间比较
      - in -> IN (...)
      - contains -> LIKE
      - bool_true / bool_false -> 1 / 0（若列为布尔/整型标志）
    - 若值无法安全解析为 SQL 比较值，则忽略该条约束（不要猜测）。

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
    - 严格以 requirements 中的 operator 与 is_hard 为准，不要重新推断数值方向或重判软硬约束。
    - passes_hard 仅根据 is_hard=true 的 requirements 判定；软约束仅用于解释与同等条件下排序。
    - matched_requirements / unmet_requirements 允许为简短文本摘要。

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
