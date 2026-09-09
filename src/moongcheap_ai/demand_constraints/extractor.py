from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace

from .classifier import ConstraintClassifier, normalize
from .facet_matcher import KiwiFacetMatcher


NO_REQUIREMENT_PATTERNS = (
    "조건 없음", "조건없음", "상관없", "아무거나 괜찮", "받아들", "수용 가능"
)
ALTERNATIVE_PATTERNS = (" 또는 ", " 혹은 ", " 중 하나")
SCOPE_REVIEW_PATTERNS = ("제외하지 말",)
FACET_RELATIONAL_PATTERNS = ("도 괜찮", "보다", "보단")
CONNECTIVE_ENDINGS = {"고", "지만", "하되", "되", "며", "는데"}
CONJUNCTIONS = {"그리고", "하지만"}
ACCEPTANCE_PATTERNS = ("받아들", "수용 가능", "감수", "검토", "고려 가능")
AVERSION_PATTERNS = ("꺼려", "선호하지 않", "별로", "그닥")
SELECTION_ACTION_FORMS = {
    "구매", "주문", "결제", "선택", "결정", "추천", "부탁", "확정", "진행",
    "찾", "고르", "사", "보이",
}
RELATION_EXCLUSION_PATTERN = re.compile(
    r"(?:제외|배제|빼|거르|걸러|필터|보이지\s*않|보여\s*주지|안\s*보이|"
    r"목록에\s*없|받을\s*수\s*없|선택[^.!?]{0,12}수\s*없|구매[^.!?]{0,12}(?:수\s*없|불가))"
)
OTHER_TARGET_PATTERN = re.compile(r"(?:다른|나머지|그\s*외|이외|아닌)\s*(?:성분|제형|형태|제품|후보|것|건|거)?")
SELECTED_VALUE_PATTERN = re.compile(
    r"^(?:은|는|이|가|을|를|으로|로)?\s*만(?:을|으로|으로만)?\b|"
    r"^(?:은|는|이|가|을|를)?\s*(?:외에는|말고는)|"
    r"^(?:으로|로)?\s*한정|^(?:으로|로)?\s*제한"
)
NEGATED_COMPLEMENT_PATTERN = re.compile(
    r"^(?:은|는|이|가|을|를)?\s*(?:아닌|아니면)[^.!?]{0,48}"
)
NON_COMMITTED_FINAL_PATTERNS = (
    re.compile(
        r"(?:빼|제외|배제|거르|걸러|숨겨)[^.!?]{0,24}(?:아|어)?도\s*"
        r"(?:될까|될지|되나|괜찮을까|괜찮은지)"
    ),
    re.compile(
        r"(?:빼|제외|배제|거르|걸러|숨겨)[^.!?]{0,28}"
        r"(?:달라는|하자는|하려는|하겠다는)[^.!?]{0,20}(?:아니|아냐|아닙)"
    ),
    re.compile(r"(?:어떨까|어떨지)[^.!?]{0,40}(?:생각|고민|궁금|모르)"),
    re.compile(r"(?:생각|고민)[^.!?]{0,16}만\s*(?:하|해|중)"),
)
FINAL_COMMITMENT_PATTERN = re.compile(
    r"(?:반드시|무조건|필수|확정|"
    r"(?:고르|고를|선택|구매|주문|빼|제외|거르|걸러)[^.!?]{0,24}"
    r"(?:주세요|줘|주십시오|할게|하겠|합니다|해요))"
)
EVENT_CANCEL_PATTERNS = (
    re.compile(r"(?:빼|제외|배제|제거|숨기|거르|걸러)[^.!?]{0,28}(?:뜻|말|의미|요청)[^.!?]{0,16}(?:아닌|아님|아니|아냐|아닙)"),
    re.compile(r"(?:빼|제외|배제|제거|숨기|거르|걸러)[^.!?]{0,20}(?:하진|하지는|하자는\s*건|하는\s*건)[^.!?]{0,12}(?:않|아닌|아님|아니)"),
    re.compile(r"(?:안\s*(?:사|받)|못\s*(?:사|받))[^.!?]{0,16}(?:겠다는|다는)[^.!?]{0,12}(?:뜻|말|의미)[^.!?]{0,12}(?:아닌|아님|아니|아냐|아닙)"),
    re.compile(r"(?:결정|확정|선택|정한|정하)[^.!?]{0,16}(?:아닌|아님|아니|못|않)"),
    re.compile(r"(?:요청|구매|살|고를|선택할)[^.!?]{0,16}(?:생각|의사|마음)[^.!?]{0,12}(?:없|아닌|아님|아니)"),
    re.compile(r"(?:취소|보류|마음을?\s*접|다시\s*생각|말았|그만)"),
)
EVENT_TENTATIVE_PATTERNS = (
    re.compile(r"(?:빼|제외|배제|제거|숨기|거르|걸러|안\s*보이|안\s*보여|보여\s*줘)[^.!?]{0,24}(?:아|어)?도\s*(?:되|괜찮)"),
    re.compile(r"(?:할|될|둘|뺄|고를|살|먹을)\s*수\s*(?:있|없는지)"),
    re.compile(r"(?:가능|괜찮|나을|좋을)[^.!?]{0,12}(?:지|까)"),
    re.compile(r"(?:어떨|어떤지|할까|될까|둘까|뺄까|고를까|살까|말까)"),
    re.compile(r"(?:궁금|고민|망설|상상|추측|모르|미정|아직|나중|혼자\s*생각|생각만|확인만|문의|여쭤|물어)"),
    re.compile(r"(?:필수|반드시|꼭)[^.!?]{0,28}(?:아니|않|없)"),
)
EVENT_DIRECT_REQUEST_PATTERN = re.compile(
    r"(?:찾아|보여|골라|추천|선택|구매|주문|빼|제외|배제|제거|숨겨|거르|걸러)"
    r"[^.!?]{0,24}(?:주세요|줘|주십시오|주시겠|주실\s*수\s*있을까요|부탁)"
)
EVENT_REMOVE_PATTERN = re.compile(
    r"(?:제외|배제|제거|사절|거부|빼|거르|걸러|필터|숨기|숨겨|안\s*보이|안\s*보여|보이지\s*않|"
    r"보여\s*주지|보여주지|받지\s*않|안\s*받|받을\s*수\s*없|주문[^.!?]{0,12}불가|"
    r"구매[^.!?]{0,12}(?:불가|수\s*없)|선택[^.!?]{0,12}수\s*없)"
)
EVENT_PREFER_PATTERN = re.compile(
    r"(?:점수|가산점|가중치|우선순위|목록[^.!?]{0,16}(?:위|상단)|동률[^.!?]{0,16}먼저)"
)
EVENT_COREFERENCE_PATTERN = re.compile(
    r"(?:해당|그|이)\s*(?:성분|제형|제품|조건|항목|조합)|그걸|그것|그쪽|실제로|결국|최종"
)

# v0.17 keeps predicate positions inside a clause. These expressions are not
# applied to v0.16, whose frozen evaluation used one event per clause.
PREDICATE_CANCEL_PATTERNS = (
    *EVENT_CANCEL_PATTERNS,
    re.compile(r"(?:빼|제외|배제|제거|숨기|거르|걸러)\s*(?:지\s*말|지는\s*말|지\s*않|는\s*(?:아닌|아님|아니))"),
    re.compile(r"(?:아니어도|아니라도|아닐지라도)[^.!?]{0,16}상관없"),
    re.compile(r"(?:조건|요청|선택|말|의견)[^.!?]{0,20}(?:취소|철회|거두|거둬|없던\s*걸|보류)"),
    re.compile(r"(?:취소|철회|거두|거둬|없던\s*걸|보류)[^.!?]{0,16}(?:할게|하겠|해\s*주|해줘|둘게)?"),
    re.compile(r"(?:잘못\s*(?:한|말한)|그\s*말[^.!?]{0,12}(?:아니|취소))"),
    re.compile(r"(?:상관없|아무거나\s*괜찮)"),
)
PREDICATE_TENTATIVE_PATTERNS = (
    *EVENT_TENTATIVE_PATTERNS,
    re.compile(r"(?:주문|구매|선택|제외|배제|필터링)?[^.!?]{0,12}(?:가능한가요|가능\s*여부|가능한지)"),
    re.compile(r"(?:정하지\s*않|결정\s*(?:안|못)|확정[^.!?]{0,8}(?:아닌|아님|아니))"),
    re.compile(r"(?:다시|더|조금\s*더)[^.!?]{0,8}(?:생각|검토|고민)"),
    re.compile(r"(?:필요|고집)[^.!?]{0,20}(?:있을까|없을|않아도|않을)"),
)
PREDICATE_MUST_PATTERN = re.compile(
    r"(?:반드시|무조건|필수|꼭|오직|절대\s*(?:조건|바꿀\s*수\s*없)|"
    r"바꿀\s*수\s*없|(?:만|으로만)[^.!?]{0,20}"
    r"(?:구매|주문|선택|포함|받|사|살|고르|찾|보여))"
)
PREDICATE_PREFER_PATTERN = re.compile(
    r"(?:점수|가산점|가중치|우선순위|순위)[^.!?]{0,28}"
    r"(?:주|줘|두|반영|계산|부여|높|올리)|"
    r"(?:우선|먼저)[^.!?]{0,20}(?:추천|보여|배치)|"
    r"(?:추천\s*)?목록[^.!?]{0,24}(?:위|상단)[^.!?]{0,16}(?:올려|높여|배치|보여)|"
    r"상위[^.!?]{0,16}(?:올려|높여|배치|보여)|"
    r"(?:더|가급적|우선적으로)?\s*선호(?:합니다|해|하)"
)
PREDICATE_COMMIT_PATTERN = re.compile(
    r"(?:확정|결정)[^.!?]{0,12}(?:할게|하겠|합니다|했|해요)|"
    r"(?:확정|결정)하겠습니다"
)
PREDICATE_COREFERENCE_PATTERN = re.compile(
    r"(?:해당|그|이|같은)\s*(?:성분|제형|제품|조건|항목|조합|횟수|주기|규격|요청|말)|"
    r"그걸|그것|그쪽|방금|실제로|결국|최종|마지막"
)
TYPED_COREFERENCE_PATTERN = re.compile(
    r"(?:해당|그|이|같은)\s*(?:성분|제형|형태|제품|조건|항목|조합|횟수|주기|규격|요청|말|"
    r"기준|방향|선택)|그걸|이걸|그것|이것|그대로|이대로|그렇게|이렇게"
)
REFERENCE_CONFIRM_PATTERN = re.compile(
    r"(?:확정|최종\s*(?:결정|확인)|두\s*조건[^.!?]{0,8}확인|결정할|결정하|진행할|진행하|(?:그걸|이걸)로\s*(?:해|결정)|그렇게\s*하|"
    r"이대로|그대로|맞습니다|조건대로|반영해|반영하|바꿔|변경해)"
)
TYPED_GLOBAL_DEFERRAL_PATTERN = re.compile(
    r"(?:조금|좀)\s*더[^.!?]{0,20}(?:살펴|보)[^.!?]{0,20}(?:정|결정|판단)|"
    r"며칠[^.!?]{0,16}더\s*(?:보|지켜|살펴)[^.!?]{0,16}(?:정|결정|판단)|"
    r"(?:자료|정보)?[^.!?]{0,12}더\s*(?:보|지켜|살펴)[^.!?]{0,16}(?:정|결정|판단)|"
    r"답변[^.!?]{0,12}(?:받|오|듣)[^.!?]{0,16}(?:확정|결정|정|판단)|"
    r"(?:상담|문의)[^.!?]{0,16}(?:받|한|후)[^.!?]{0,16}(?:확정|결정|정|판단)|"
    r"검토[^.!?]{0,16}(?:결과|답|회신)[^.!?]{0,16}(?:나오|받|오)[^.!?]{0,12}(?:확정|결정|정|판단)|"
    r"(?:담당자\s*)?회신[^.!?]{0,12}(?:받|오)[^.!?]{0,16}(?:확정|결정|정|판단)|"
    r"(?:회의|담당자|주말|자료|정보|검토|확인|알아보|다음번)[^.!?]{0,28}"
    r"(?:뒤|후|끝나|마치|거치|지나|다음)[^.!?]{0,24}(?:정|결정|판단|결론|답|확정|선택|고르)"
)
TYPED_TEMPORAL_TOKEN_DEFERRAL_PATTERN = re.compile(
    r"(?:나중|이따|다음|추후)[^.!?]{0,32}?(?:정|결정|판단|결론|답|확정|고르|선택|미루|보려|고민)"
)
TYPED_UNRESOLVED_TAIL_PATTERN = re.compile(
    r"(?:아직|일단)[^.!?]{0,16}(?:확정|결정|정)[^.!?]{0,8}(?:아니|않|못)|"
    r"(?:보류|미루|남겨\s*두|확정\s*못|정하지\s*않)"
)
TYPED_CURRENT_OVERRIDE_PATTERN = re.compile(
    r"(?:(?:지금|현재|바로|당장|우선)[^.!?]{0,32}"
    r"(?:반드시|필수|무조건|가산점|우선순위|상단|상위|위쪽|맨\s*위|제외|빼|삭제|"
    r"순위|높여|올려|우대|우선해|위주로|먼저\s*추천|포함|확정|결정|제거|숨겨|가려|추천하지|선택하지|사지\s*않|"
    r"만\s*(?:사|받|구매|선택)|그렇게\s*하)|"
    r"(?:했지만|했으나|했는데|하려다|려다)[^.!?]{0,28}"
    r"(?:반드시|필수|무조건|가산점|우선순위|상단|맨\s*위|제외|빼|삭제|"
    r"순위|높여|우대|포함|확정|결정|추천하지|선택하지|사지\s*않|"
    r"만\s*(?:사|받|구매|선택))|"
    r"(?:마음|생각)[^.!?]{0,10}(?:바꾸|바꿔|바뀌)|다시\s*생각[^.!?]{0,16}"
    r"(?:반드시|필수|무조건|가산점|제외|포함))"
)
FACET_RELATION_COMPLEMENT_REFERENCE_PATTERN = re.compile(
    r"(?:다른|나머지|그\s*밖|그\s*외|이외|이를\s*제외한|"
    r"(?:그|이)\s*(?:조합|조건|값|형태|제형|성분|횟수)\s+(?:외|이외)|"
    r"(?:[^.!?,\s]+\s+){1,3}(?:아닌|아니면|아니라면|외에는|외의|외|이외의?))"
)
FACET_RELATION_COMPLEMENT_SELECTION_PATTERN = re.compile(
    r"(?:다른|나머지|그\s*밖|그\s*외|이외)[^.!?]{0,24}?"
    r"(?:만|위주로)[^.!?]{0,16}(?:보여|보이|남겨|선택|골라|받|찾|검색|추천)"
)
FACET_RELATION_COMPLEMENT_POSITIVE_TAIL_PATTERN = re.compile(
    r"(?:로만|으로만|위주로)[^.!?]{0,16}(?:보여|보이|남겨|선택|골라|받|찾|검색|추천)"
)
FACET_RELATION_NEGATED_STATE_PATTERN = re.compile(
    r"(?:(?:절대|아예|무조건)?[^.!?]{0,12}(?:안|않)\s*(?:들어가|들어\s*있|함유|포함)[^.!?]{0,8}(?:어야|은|않)?|"
    r"(?:절대|아예|무조건)?[^.!?]{0,16}(?:들어가|들어있|함유|포함)[^.!?]{0,10}"
    r"(?:지\s*않아야|지\s*않아|지\s*않은|으면\s*안\s*되|면\s*안\s*되))"
)
FACET_RELATION_ELLIPTICAL_MUST_PATTERN = re.compile(
    r"(?:으로|로)만\s*(?:주세요|줘|주십시오|주시고|주고|알려|제안|보내|받을래요|할게요?)"
)
PREDICATE_FRAME_RELATION_PATTERN = re.compile(
    r"(?:아닌|아니면|아니라면|말고|(?<!제)외(?:에는|의|는)?|이외의?|그\s*외|그\s*밖|다른|나머지|"
    r"(?:들어가|들어\s*있|포함|함유)[^.!?]{0,8}(?:지\s*)?않은|없는)"
)
PREDICATE_FRAME_REMOVE_ACTION_PATTERN = re.compile(
    r"(?:제외|배제|제거|빼|거르|걸러|필터|숨기|숨겨|감추|감춰|가리|가려|지우|없애|"
    r"안\s*보이|안\s*보여|보이지\s*않|나타나지\s*않|필요\s*없)"
)
PREDICATE_FRAME_SELECT_ACTION_PATTERN = re.compile(
    r"(?:(?:만|으로만|로만|위주로)[^.!?]{0,24}"
    r"(?:보여|보이|찾|검색|골라|고르|선택|남기|추천|구성|추려|받|살|사)|"
    r"(?:으로|로)[^.!?]{0,12}(?:보여|보이|찾|검색|골라|고르|선택|남기|추천|구성|추려|받)|"
    r"(?:보여|찾|검색|골라|고르|선택|남기|추천|구성|추려)[^.!?]{0,12}(?:만|으로만|로만))"
)
PREDICATE_FRAME_COMPLEMENT_POOL_PATTERN = re.compile(
    r"(?:아닌|아니라면|말고|(?<!제)외(?:의|는)?|이외의?|다른|나머지)"
    r"[^.!?]{0,28}(?:중에서|중)(?:\s|,|$)"
)
PREDICATE_FRAME_NAMED_MUST_PATTERN = re.compile(
    r"^[^.!?]{0,24}(?:반드시|무조건|필수|꼭|오직|(?:만|으로만|로만)[^.!?]{0,16}"
    r"(?:보여|보이|찾|검색|골라|고르|선택|남기|포함|받|살|사))"
)
PREDICATE_FRAME_NAMED_EXCLUDE_PATTERN = re.compile(
    r"^[^.!?]{0,20}(?:제외|배제|제거|빼|거르|걸러|숨기|감추|가리|지우|없애|"
    r"추천[^.!?]{0,8}(?:않|말)|포함[^.!?]{0,8}(?:않|말))"
)
OCCURRENCE_NAMED_NEGATED_SELECTION_PATTERN = re.compile(
    r"^[^.!?]{0,20}(?:절대|아예|전혀)?[^.!?]{0,8}"
    r"(?:사|구매|선택|고르)[^.!?]{0,8}(?:지\s*않|지\s*말|않을|안\s*사)"
)
PREDICATE_FRAME_NON_COMMITTED_PATTERNS = (
    re.compile(r"(?:요청|말|의견|선택|결정|확정)[^.!?]{0,24}(?:취소|철회|없던\s*걸|보류)"),
    re.compile(r"(?:취소|철회|없던\s*걸|보류)[^.!?]{0,16}(?:해|하겠|할게|합니다)?"),
    re.compile(r"동의[^.!?]{0,20}(?:아니|아닌|아님|아닙|않)"),
    re.compile(
        r"(?:선택|결정|확정)(?:한|하겠다는|한다는|하려는|할)?[^.!?]{0,16}"
        r"(?:뜻|건|것|상태)(?:은|이|도)?[^.!?]{0,10}(?:아니|아닌|아님|아닙|않)"
    ),
    re.compile(r"(?:선택|결정|확정)(?:은|이)?\s*아직[^.!?]{0,12}(?:아니|아님|아닙|않|못)"),
    re.compile(r"(?:아직|여전히)[^.!?]{0,48}(?:아니|아닌|아님|아닙|못\s*정|결정\s*못|고민\s*중)"),
    re.compile(r"(?:할지\s*말지|수\s*있는지|가능한지|되는지)[^.!?]{0,48}(?:여부만|문의|묻|물어|여쭤|고민)"),
    re.compile(r"(?:만약|가정)[^.!?]{0,80}(?:여쭤|문의|질문|어떻게|어떨)"),
    re.compile(r"(?:문의|상담|답변|회신|검토\s*결과)[^.!?]{0,40}(?:결정|확정|판단|정할|정하겠)"),
    re.compile(r"(?:논의|회의|검토)[^.!?]{0,24}(?:뒤|후)[^.!?]{0,24}(?:결정|확정|판단|정할|정하겠)"),
    re.compile(r"(?:선택|결정|확정)(?:은|이)?\s*아직(?:이|임|인)"),
    re.compile(r"(?:아직[^.!?]{0,20})?결정[^.!?]{0,8}하지\s*못"),
    re.compile(r"동의\s*(?:안|못)"),
    re.compile(
        r"(?:제외|제거|빼|숨기|선택|남기)[^.!?]{0,16}(?:할지|지는)"
        r"[^.!?]{0,20}(?:아직|미정)[^.!?]{0,16}(?:정하지\s*않|결정[^.!?]{0,6}못|아니)"
    ),
)
PREDICATE_FRAME_CURRENT_MARKER_PATTERN = re.compile(
    r"(?:지금|이제|현재|바로|당장|최종(?:적으로)?|새로|결국)"
)
FACET_RELATION_TARGETLESS_TEMPORAL_PATTERN = re.compile(
    r"(?:나중|이따|추후|아직|다시)[^.!?]{0,24}(?:고르|선택|정|결정|알려|답)|"
    r"(?:미루|미뤄|보류|결론[^.!?]{0,8}못)"
)
NON_CONSTRAINT_INQUIRY_PATTERN = re.compile(
    r"(?:성분표|원산지|배송|보관|가격|포장|브랜드|복용\s*시간|몇\s*시)[^.!?]{0,28}"
    r"(?:확인|문의|궁금|알\s*수|어떻|물어|알려|질문)"
)
TYPED_FINAL_UNRESOLVED_PATTERN = re.compile(
    r"(?:보류|미루|남겨\s*두|정하지\s*않|확정\s*못)[^.!?]{0,12}(?:하겠습니다|할게요|합니다|해요|습니다)?[.!?]*$"
)
FACET_REFERENCE_PATTERN = re.compile(
    r"(?:해당|그|이)\s*(성분|제형|형태|횟수|주기)"
)
FACET_REFERENCE_NAMES = {
    "성분": "functional_ingredients",
    "제형": "product_form",
    "형태": "product_form",
    "횟수": "daily_frequency",
    "주기": "daily_frequency",
}
COMPLEMENT_REMOVAL_PATTERN = re.compile(
    r"(?:다른|나머지|그\s*외|이외)[^.!?]{0,24}"
    r"(?:빼|제외|배제|제거|숨기|거르|삭제|없애|지우)"
)
REFERENTIAL_COMPLEMENT_REMOVAL_PATTERN = re.compile(
    r"(?:다른|나머지|그\s*외|이외|이를\s*제외한)[^.!?]{0,36}"
    r"(?:빼|제외|배제|제거|숨기|숨겨|감추|가리|거르|삭제|없애|지우|지워|"
    r"노출[^.!?]{0,8}(?:않|말|마)|추천[^.!?]{0,8}(?:않|말|마|안\s*해))"
)
TYPED_COMPLEMENT_REFERENCE_PATTERN = re.compile(
    r"(?:다른|나머지|그\s*외|그\s*밖|이외|이와\s*다른|이것이\s*아닌|이를\s*제외한|"
    r"복용\s*횟수가\s*다른|섭취\s*횟수가\s*다른)"
)
TYPED_COMPLEMENT_ACTION_PATTERN = re.compile(
    r"(?:빼|제외|배제|제거|숨기|숨겨|감추|감춰|가리|거르|걸러|삭제|없애|지우|지워|"
    r"안\s*보이|보이지\s*않|노출[^.!?]{0,10}(?:않|말|마)|"
    r"추천[^.!?]{0,10}(?:않|말|마|안\s*해)|표시[^.!?]{0,10}(?:않|말|마)|"
    r"목록[^.!?]{0,10}넣지)"
)
GENERIC_FACET_SELECTION_PATTERN = re.compile(
    r"(?:(?<!것)으로|(?<!것으)로)(?:만)?[^.!?]{0,8}"
    r"(?:할게|하겠|해야|합니다|해요|정할게|정하겠)"
)

# v0.27 does not use these expressions to decide a constraint polarity.  They
# are negative evidence: a constraint mentioned inside a question, hypothesis,
# quotation, consultation, cancellation, or deferred decision is not safe to
# auto-apply unless a later explicit predicate proves the final state.
PROOF_UNRESOLVED_MODALITY_PATTERNS = (
    re.compile(
        r"(?:가정|문의|여쭤|상담|검토|고민|망설|미정|보류|아직|나중|추후|"
        r"확인만|상담만|검토\s*중|결정되지\s*않|결정[^.!?]{0,12}(?:아니|않|못)|"
        r"요청[^.!?]{0,12}(?:아니|않)|정식[^.!?]{0,12}요청[^.!?]{0,8}(?:아니|않))"
    ),
    re.compile(
        r"(?:수\s*있는지|가능한지|할지|될지|볼지|고를지|선택할지|"
        r"볼\s*경우|한다면|만약|어떨지|어떨까)"
    ),
    re.compile(
        r"(?:취소|철회|착오|신경\s*쓰지|동의[^.!?]{0,10}(?:안|않)|"
        r"내키지\s*않|제안[^.!?]{0,16}(?:반대|내키지))"
    ),
)
PROOF_CURRENT_MARKER_PATTERN = re.compile(
    r"(?:지금|이제|현재|바로|당장|최종(?:적으로)?|결국|새로|"
    r"할게요?|하겠습니다|해주세요|해\s*주세요|해줘|주십시오|부탁합니다)"
)
PROOF_FILTER_ACTION_PATTERN = re.compile(r"(?:필터|거르|걸러)")
PROOF_SELECTED_PARTICLE_PATTERN = re.compile(r"(?:으로|로)?만")
SPEAKER_THIRD_PARTY_PATTERN = re.compile(
    r"(?:남이|남들은?|누가|타인|친구|지인|아는\s*(?:사람|분)|"
    r"주변(?:에서|에서는|사람|분)?|다른\s*(?:분|사람)|"
    r"팀원|동료|직장\s*동료|같이\s*일하는\s*동료|가족|담당자)"
)
SPEAKER_REPORTED_ACTION_PATTERN = re.compile(
    r"(?:말(?:하|했|을|이라)|추천|권하|권했|제안|인용|들었|하던데|하던\s*말)"
)
SPEAKER_REJECTION_PATTERN = re.compile(
    r"(?:동의[^.!?]{0,12}(?:아니|아냐|않|못)|반대|내키지\s*않|"
    r"따르지\s*않|받아들이지\s*않|수용하지\s*않|무관(?:하게|한)|"
    r"상관없는|생각(?:은|이)?[^.!?]{0,12}다르|그건\s*좀|"
    r"굳이[^.!?]{0,12}(?:싶지|않))"
)
SPEAKER_ACCEPTANCE_PATTERN = re.compile(
    r"(?:(?:저는|저도|제가|나는|나도|내가|전|난)[^.!?]{0,48}"
    r"(?:동의|받아들|그대로\s*따르|따르|따를|수용|찬성|맞는\s*것\s*같|"
    r"괜찮을\s*것\s*같)|(?:받아들이|수용하|따르)기로)"
)

EXPLICIT_FILTER_KEEP_AFTER_VALUE_PATTERN = re.compile(
    r"[^.!?]{0,72}(?:만|오직)[^.!?]{0,36}"
    r"(?:남도록|남겨|남기|유지|나오게|보이게|보여|볼게|확인|고르|골라|선택)"
)
EXPLICIT_FILTER_COREFERENTIAL_KEEP_PATTERN = re.compile(
    r"(?:해당(?:되는)?\s*(?:것|제품|후보)|이\s*조건(?:에\s*부합하는)?\s*(?:것|제품|후보)|"
    r"그\s*조건(?:에\s*맞는)?\s*(?:것|제품|후보))[^.!?]{0,16}만[^.!?]{0,20}"
    r"(?:남|보|확인|고르|골라|선택)"
)
EXPLICIT_FILTER_REMOVE_AFTER_VALUE_PATTERN = re.compile(
    r"[^.!?]{0,64}(?:필터(?:링)?|거르|걸러)[^.!?]{0,32}"
    r"(?:전부\s*)?(?:제외|배제|빼|없애|제거|숨겨|목록에서\s*빼)"
)
EXPLICIT_FILTER_DIRECT_REMOVE_PATTERN = re.compile(
    r"[^.!?]{0,36}(?:전부\s*)?(?:걸러내|걸러\s*내)"
)
EXPLICIT_FILTER_COMPLEMENT_PATTERN = re.compile(
    r"^\s*(?:은|는|이|가|을|를)?\s*(?:외|이외|아닌|이\s*아닌)"
)
REPORTED_COMPLEMENT_EVENT_PATTERN = re.compile(
    r"(?:(?:자|라|다|냐)고|(?:다|라)길래|(?:다|라)며|대서)"
    r"[^.!?]{0,28}(?:말|얘기|하|했|제안|추천|권|조언|전하|들었)"
)
STRONG_USER_FINAL_ACTION_PATTERN = re.compile(
    r"(?:선택|포함|넣|보여|보이|골라|고르|찾|추천|배치|높여|올려|"
    r"가산점|제외|배제|빼|제거|유지|남겨|확정)"
    r"[^.!?]{0,28}(?:주세요|줘|주십시오|주시기\s*바랍니다|"
    r"주시면\s*(?:됩니다|좋겠습니다)|하겠습니다|하지\s*않겠습니다|"
    r"않겠습니다|하지\s*마(?:세요)?|바랍니다)"
)
WEAK_USER_TAIL_MODALITY_PATTERN = re.compile(
    r"(?:것\s*같|듯(?:해|합니다)|살펴|검토|고민|망설|문의|궁금|"
    r"어떨|괜찮을지|할지|볼까|해볼까|보고\s*싶|찾아보고\s*싶|"
    r"한번\s*보|일단\s*보)"
)
TYPED_TAIL_UNRESOLVED_MODALITY_PATTERN = re.compile(
    r"(?:것\s*같|듯(?:해|합니다)|살펴봐야|검토|고민|망설|문의|궁금|"
    r"어떨|괜찮을지|할지|볼까|해볼까|한번\s*보|일단\s*보|"
    r"아직|나중|추후|보류|미정|무관|구경|"
    r"싶지(?:는)?\s*않|고집[^.!?]{0,16}않|생각(?:은|이)?\s*없)"
)
REPORTED_TAIL_EMBEDDING_PATTERN = re.compile(
    r"(?:(?:자|라|다|냐)고|(?:다|라)며)[^.!?]{0,28}"
    r"(?:말|얘기|하|했|제안|추천|권|조언|전하|들었)"
)
OCCURRENCE_SOFT_STRENGTH_PATTERN = re.compile(
    r"(?:가급적(?:이면)?|가능하면|이왕이면|되도록|웬만하면)"
)
OCCURRENCE_SOFT_STRENGTH_PATTERN_V037 = re.compile(
    r"(?:가급적(?:이면)?|가능(?:하면|하다면)|이왕이면|되도록(?:이면)?|"
    r"될\s*수\s*있으면|웬만하면)"
)
OCCURRENCE_HARD_STRENGTH_PATTERN = re.compile(
    r"(?:반드시|무조건|필수|꼭)"
)


@dataclass(frozen=True)
class FilterOperation:
    criterion_span: tuple[int, int]
    predicate_span: tuple[int, int]
    case_role: str
    result_action: str
    source: str


@dataclass(frozen=True)
class SpeakerScope:
    owner: str
    acceptance: str
    evidence_span: tuple[int, int]
    reported_span: tuple[int, int] | None = None
    user_tail_span: tuple[int, int] | None = None
    tail_proof_source: str | None = None


@dataclass(frozen=True)
class ConstraintProof:
    taxonomy_span: tuple[int, int]
    predicate_span: tuple[int, int]
    argument_role: str
    set_operation: str
    polarity_source: str
    modality_scope: str
    final_state_order: int
    filter_operation: FilterOperation | None = None
    speaker_scope: SpeakerScope | None = None


@dataclass(frozen=True)
class FacetConstraint:
    facet_name: str
    value_code: int
    value: str
    constraint_type: str
    evidence_clause: str
    proof: ConstraintProof | None = None


@dataclass(frozen=True)
class FacetEvent:
    facet_name: str
    value_code: int
    value: str
    polarity: str | None
    modality: str
    order: int
    evidence_clause: str
    target_role: str = "NAMED_VALUE"
    anchor_facet_name: str | None = None
    anchor_value_code: int | None = None


@dataclass(frozen=True)
class PredicateSignal:
    start: int
    position: int
    modality: str
    polarity: str | None
    marker: str
    source: str


@dataclass(frozen=True)
class PredicateFrame:
    facet_name: str
    value_code: int
    value: str
    action: str
    target_role: str
    argument_start: int
    argument_end: int
    modality: str
    temporal: str
    negated: bool
    polarity: str
    evidence_clause: str


@dataclass(frozen=True)
class StrengthModifier:
    start: int
    end: int
    strength: str
    facet_name: str
    value_code: int
    occurrence_span: tuple[int, int]
    scope_end: int


@dataclass(frozen=True)
class ActionEvidence:
    facet_name: str
    value_code: int
    value: str
    taxonomy_span: tuple[int, int]
    predicate_span: tuple[int, int]
    action: str
    polarity: str
    source: str
    evidence_clause: str


@dataclass(frozen=True)
class NegativePreferenceEvidence:
    facet_name: str
    value_code: int
    value: str
    taxonomy_span: tuple[int, int]
    modifier_span: tuple[int, int]
    predicate_span: tuple[int, int]
    source: str


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    constraints: tuple[FacetConstraint, ...]
    warnings: tuple[str, ...]
    clauses: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "constraints": [asdict(item) for item in self.constraints],
            "warnings": list(self.warnings),
            "clauses": list(self.clauses),
        }


class ConstraintExtractor:
    def __init__(self, matcher: KiwiFacetMatcher, classifier: ConstraintClassifier) -> None:
        self.matcher = matcher
        self.classifier = classifier
        self.kiwi = matcher.kiwi

    @staticmethod
    def _has_user_commitment(text: str) -> bool:
        value = normalize(text)
        explicit = (
            "반드시", "무조건", "꼭", "필수", "이어야", "여야", "만 고르", "만 고를",
            "만 선택", "만 구매", "만 주문", "원합니다", "원해요", "할게요",
            "하겠습니다", "확정",
        )
        if any(marker in value for marker in explicit):
            return True
        return bool(re.search(
            r"(?:저는|나는|전|난|제가|내가)[^.!?]{0,48}"
            r"(?:만[^.!?]{0,16}(?:고르|고를|선택|구매|주문)|(?:고르|고를|선택|구매|주문)[^.!?]{0,12}(?:할게|하겠|확정))",
            value,
        ))

    def _is_reported_non_user_context(self, text: str) -> bool:
        """Route another person's opinion or an uncommitted recollection to REVIEW."""
        if not self.classifier.reported_context_guard:
            return False
        value = normalize(text)
        reported = any(
            marker in value
            for marker in (
                "추천받", "권해", "권하", "들었", "듣기", "말하", "하더라고",
                "기억", "적이 있", "얘기", "이야기",
            )
        )
        third_party = any(
            marker in value
            for marker in ("지인", "친구", "주변", "다른 사람", "아는 분", "가족", "동료")
        )
        uncertain = any(
            marker in value
            for marker in (
                "아직", "모르", "정하진 않", "결정하지 않", "구매 의사", "고민",
                "생각이 없", "확정은 아니",
            )
        )
        if "어떨까" in value and any(marker in value for marker in ("생각", "모르", "궁금")):
            return True
        if reported and uncertain:
            return True
        if (reported or third_party) and not self._has_user_commitment(value):
            return True
        return False

    def _final_commitment_state(self, category_id: str, text: str) -> str:
        """Detect permission, hypothesis, or retraction before extraction.

        A later clause restores commitment only when it explicitly commits every
        taxonomy value mentioned in the utterance. A final decision about B must
        not accidentally commit an earlier hypothetical A.
        """
        if not self.classifier.final_commitment_guard:
            return "NONE"
        value = normalize(text)
        matched = [
            match
            for pattern in NON_COMMITTED_FINAL_PATTERNS
            if (match := pattern.search(value)) is not None
        ]
        if not matched:
            return "NONE"
        last_non_commit_end = max(match.end() for match in matched)
        tail = value[last_non_commit_end:].strip(" ,.;!?")
        if not tail or not FINAL_COMMITMENT_PATTERN.search(tail):
            return "NON_COMMITTED"
        all_facets = {
            (item.facet.facet_name, item.facet.value_code)
            for item in self.matcher.occurrences(category_id, text)
        }
        tail_facets = {
            (item.facet.facet_name, item.facet.value_code)
            for item in self.matcher.occurrences(category_id, tail)
        }
        if all_facets and all_facets.issubset(tail_facets):
            return "RESTORED"
        return "NON_COMMITTED"

    def _relation_override(
        self,
        category_id: str,
        clause: str,
        facet_name: str,
        value_code: int,
    ) -> str | None:
        """Resolve a named value kept by excluding its complement.

        The exclusion verb may be closer to the text than the positive selection,
        but its grammatical target is `다른/나머지/아닌 제품`, not the matched
        taxonomy value itself.
        """
        if not self.classifier.local_relation_scope:
            return None
        occurrences = [
            item
            for item in self.matcher.occurrences(category_id, clause)
            if item.facet.facet_name == facet_name and item.facet.value_code == value_code
        ]
        for occurrence in occurrences:
            before = normalize(clause[:occurrence.start])
            after = normalize(clause[occurrence.end:])
            if re.search(
                r"^(?:은|는|이|가|을|를)?[^.!?]{0,24}(?:빠지|누락|제외되)[^.!?]{0,16}"
                r"(?:안\s*(?:되|돼|됩)|수\s*없|불가)",
                after,
            ):
                return "MUST"
            if NEGATED_COMPLEMENT_PATTERN.search(after) and RELATION_EXCLUSION_PATTERN.search(after):
                return "MUST"
            selected = SELECTED_VALUE_PATTERN.search(after)
            if selected and before.endswith("오직"):
                return "MUST"
            other = OTHER_TARGET_PATTERN.search(after)
            excluded = RELATION_EXCLUSION_PATTERN.search(after)
            if selected and other and excluded and selected.start() <= other.start() <= excluded.start():
                return "MUST"
            if re.search(r"^(?:은|는|이|가|을|를)?\s*(?:외|이외)[^.!?]{0,48}", after) and excluded:
                return "MUST"
            if self.classifier.referential_complement_temporal_resolution:
                selected_before_complement = re.search(
                    r"^[^.!?]{0,16}만[^.!?]{0,32}(?:다른|나머지|그\s*외|이외|이를\s*제외한)",
                    after,
                )
                if selected_before_complement and REFERENTIAL_COMPLEMENT_REMOVAL_PATTERN.search(after):
                    return "MUST"
            if self.classifier.typed_reference_event_roles:
                selected_before_complement = re.search(r"^[^.!?]{0,20}만", after)
                if (
                    selected_before_complement
                    and TYPED_COMPLEMENT_REFERENCE_PATTERN.search(after)
                    and TYPED_COMPLEMENT_ACTION_PATTERN.search(after)
                ):
                    return "MUST"
        return None

    def _is_complement_removal(self, clause: str) -> bool:
        value = normalize(clause)
        if COMPLEMENT_REMOVAL_PATTERN.search(value):
            return True
        if self.classifier.typed_reference_event_roles:
            return bool(
                TYPED_COMPLEMENT_REFERENCE_PATTERN.search(value)
                and TYPED_COMPLEMENT_ACTION_PATTERN.search(value)
            )
        return bool(
            self.classifier.referential_complement_temporal_resolution
            and REFERENTIAL_COMPLEMENT_REMOVAL_PATTERN.search(value)
        )

    def _event_modality(self, clause: str, classification_type: str) -> str:
        value = normalize(clause)
        if any(pattern.search(value) for pattern in EVENT_CANCEL_PATTERNS):
            return "CANCELLED"
        if any(pattern.search(value) for pattern in EVENT_TENTATIVE_PATTERNS):
            return "TENTATIVE"
        if EVENT_DIRECT_REQUEST_PATTERN.search(value):
            return "COMMITTED"
        if classification_type == "REVIEW":
            return "TENTATIVE"
        return "COMMITTED"

    @staticmethod
    def _event_polarity(clause: str, classification_type: str) -> str | None:
        value = normalize(clause)
        if EVENT_REMOVE_PATTERN.search(value):
            return "EXCLUDE"
        if EVENT_PREFER_PATTERN.search(value):
            return "PREFER"
        if classification_type in {"MUST", "PREFER", "EXCLUDE"}:
            return classification_type
        return None

    @staticmethod
    def _predicate_signals(clause: str) -> tuple[PredicateSignal, ...]:
        """Collect ordered action/modality signals without collapsing a clause."""
        value = normalize(clause)
        signals: list[PredicateSignal] = []

        def add(
            pattern: re.Pattern[str],
            modality: str,
            polarity: str | None,
            source: str,
        ) -> None:
            for match in pattern.finditer(value):
                signals.append(PredicateSignal(
                    start=match.start(),
                    position=match.end(),
                    modality=modality,
                    polarity=polarity,
                    marker=match.group(0),
                    source=source,
                ))

        add(EVENT_REMOVE_PATTERN, "COMMITTED", "EXCLUDE", "REGEX_REMOVE")
        add(PREDICATE_PREFER_PATTERN, "COMMITTED", "PREFER", "REGEX_RANK")
        add(PREDICATE_MUST_PATTERN, "COMMITTED", "MUST", "REGEX_MUST")
        add(EVENT_DIRECT_REQUEST_PATTERN, "COMMITTED", None, "REGEX_DIRECT")
        add(PREDICATE_COMMIT_PATTERN, "COMMITTED", None, "REGEX_COMMIT")
        for pattern in PREDICATE_CANCEL_PATTERNS:
            add(pattern, "CANCELLED", None, "REGEX_CANCEL")
        for pattern in PREDICATE_TENTATIVE_PATTERNS:
            add(pattern, "TENTATIVE", None, "REGEX_TENTATIVE")

        # When two signals end at the same character, unresolved modality wins.
        # A question/cancellation span commonly contains the removal word that it
        # is questioning or retracting.
        modality_order = {"COMMITTED": 0, "TENTATIVE": 1, "CANCELLED": 2}
        return tuple(sorted(signals, key=lambda item: (
            item.position,
            modality_order[item.modality],
        )))

    def _morphological_predicate_signals(
        self,
        clause: str,
    ) -> tuple[PredicateSignal, ...]:
        """Augment regex signals with Kiwi predicate heads and question endings.

        In particular, discard a regex commitment that stretches across a
        question ending to a later generic `해줘`. The semantic action before
        `-는지/-ㄹ까` belongs to the question, not to a committed constraint.
        """
        tokens = tuple(self.kiwi.tokenize(clause))
        forms = tuple(token.form for token in tokens)
        question_fragments = (
            "는지", "ᆫ지", "ㄴ지", "을지", "ᆯ지",
            "을까", "ᆯ까", "을까요", "ᆯ까요",
        )
        question_positions = {
            token.start + token.len
            for token in tokens
            if token.tag in {"EC", "EF", "ETM"}
            and any(fragment in token.form for fragment in question_fragments)
        }
        if self.classifier.ending_frame_question_scope:
            interrogative_finals = (
                "습니까", "나요", "ㄴ가요", "ᆫ가요", "는가요",
                "을까요", "ㄹ까요", "ᆯ까요", "까요",
            )
            for index, token in enumerate(tokens):
                if token.tag != "EF" or not token.form.endswith(interrogative_finals):
                    continue
                preceding = tokens[max(0, index - 3):index]
                if any(item.tag == "EP" and item.form == "겠" for item in preceding):
                    question_positions.add(token.start + token.len)
        question_positions = tuple(sorted(question_positions))
        signals = [
            signal
            for signal in self._predicate_signals(clause)
            if not (
                signal.modality == "COMMITTED"
                and any(signal.start < position < signal.position for position in question_positions)
            )
        ]

        def add_token(
            index: int,
            modality: str,
            polarity: str | None,
            source: str,
            position: int | None = None,
        ) -> None:
            token = tokens[index]
            signals.append(PredicateSignal(
                start=token.start,
                position=position or token.start + token.len,
                modality=modality,
                polarity=polarity,
                marker=token.form,
                source=source,
            ))

        # Grammatical question endings close the immediately preceding action.
        for index, token in enumerate(tokens):
            if token.start + token.len in question_positions:
                add_token(index, "TENTATIVE", None, "MORPH_QUESTION_ENDING")

        inquiry_heads = {
            "묻", "궁금", "문의", "확인", "여쭙", "의견", "여부", "방법",
            "알리", "알", "알아보",
        }
        cancel_heads = {"취소", "철회", "보류", "미루", "거두", "거둬", "접"}
        removal_heads = {
            "빼", "제외", "배제", "제거", "숨기", "거르", "걸러내",
            "필터", "필터링", "삭제",
        }
        selection_heads = {
            "선택", "주문", "구매", "포함", "고르", "골라내", "받", "사", "살", "넣",
        }
        ranking_markers = {
            "점수", "가산점", "가중치", "순위", "우선순위", "상단", "위쪽",
            "상위", "우선", "먼저", "동률",
        }
        ranking_actions = {"올리", "높이", "띄우", "두", "배치", "보이", "주"}

        for index, token in enumerate(tokens):
            form = token.form
            if form in inquiry_heads:
                add_token(index, "TENTATIVE", None, "MORPH_INQUIRY_HEAD")
            if form in cancel_heads:
                add_token(index, "CANCELLED", None, "MORPH_CANCEL_HEAD")
            if form == "괜찮" and any(item in forms[max(0, index - 5):index] for item in {"아무", "상관없"}):
                add_token(index, "CANCELLED", None, "MORPH_INDIFFERENCE")

            if form in ranking_markers:
                add_token(index, "COMMITTED", "PREFER", "MORPH_RANK_MARKER")
            if form in ranking_actions:
                nearby = forms[max(0, index - 8):min(len(forms), index + 4)]
                if any(item in ranking_markers for item in nearby):
                    add_token(index, "COMMITTED", "PREFER", "MORPH_RANK_ACTION")

            if form in removal_heads:
                add_token(index, "COMMITTED", "EXCLUDE", "MORPH_REMOVE_HEAD")

            if form in selection_heads:
                before = forms[max(0, index - 2):index]
                after = forms[index + 1:min(len(forms), index + 6)]
                negated = (
                    "안" in before or "못" in before
                    or "안" in after or "못" in after or "않" in after
                )
                if negated:
                    negative_position = max(
                        (
                            item.start + item.len
                            for item in tokens[index:min(len(tokens), index + 6)]
                            if item.form == "않"
                        ),
                        default=token.start + token.len,
                    )
                    add_token(
                        index,
                        "COMMITTED",
                        "EXCLUDE",
                        "MORPH_NEGATED_SELECTION",
                        negative_position,
                    )
                else:
                    add_token(index, "COMMITTED", "MUST", "MORPH_SELECTION_HEAD")

        # Nominal `변경 불가` is the compact form of a non-negotiable MUST.
        for index, token in enumerate(tokens):
            if token.form == "불가" and "변경" in forms[max(0, index - 2):index]:
                add_token(index, "COMMITTED", "MUST", "MORPH_CHANGE_IMPOSSIBLE")
            if token.form == "결정":
                before = forms[max(0, index - 10):index]
                if "뒤" in before and any(item in before for item in {"고민", "생각", "검토"}):
                    add_token(
                        index,
                        "TENTATIVE",
                        None,
                        "MORPH_DEFERRED_DECISION",
                        len(clause) + 1,
                    )

        modality_order = {"COMMITTED": 0, "TENTATIVE": 1, "CANCELLED": 2}
        return tuple(sorted(signals, key=lambda item: (
            item.position,
            modality_order[item.modality],
        )))

    def _framed_predicate_signals(
        self,
        clause: str,
    ) -> tuple[PredicateSignal, ...]:
        """Bind action heads to negation, temporal scope, and argument role."""
        signals = list(self._morphological_predicate_signals(clause))
        tokens = tuple(self.kiwi.tokenize(clause))
        forms = tuple(token.form for token in tokens)

        def add(
            index: int,
            modality: str,
            polarity: str | None,
            source: str,
            position: int | None = None,
        ) -> None:
            token = tokens[index]
            signals.append(PredicateSignal(
                start=token.start,
                position=position or token.start + token.len,
                modality=modality,
                polarity=polarity,
                marker=token.form,
                source=source,
            ))

        removal_lemmas = {"없애", "지우", "가리", "감추", "치우"}
        for index, token in enumerate(tokens):
            if token.form in removal_lemmas:
                add(index, "COMMITTED", "EXCLUDE", "FRAME_REMOVE_LEMMA")

            if self.classifier.typed_user_tail_modality:
                after_tokens = tokens[index + 1:min(len(tokens), index + 5)]
                after_forms = tuple(item.form for item in after_tokens)
                final_position = max(
                    (
                        item.start + item.len
                        for item in after_tokens
                        if item.tag == "EF"
                    ),
                    default=token.start + token.len,
                )
                if token.form == "좋" and "겠" in after_forms:
                    add(
                        index,
                        "COMMITTED",
                        "PREFER",
                        "TYPED_DESIDERATIVE_PREFERENCE",
                        final_position,
                    )
                if token.form == "싶":
                    before = forms[max(0, index - 10):index]
                    has_strength_modifier = bool(
                        self.classifier.facet_strength_modifier
                        and any(
                            item in before
                            for item in {
                                "가급적", "가능", "이왕", "이왕이면", "되도록", "웬만하면"
                            }
                        )
                    )
                    if before and before[-1] == "고":
                        action = before[-2] if len(before) >= 2 else ""
                        compound_action = (
                            before[-3]
                            if len(before) >= 3 and action == "하"
                            else action
                        )
                        if compound_action in {
                            "빼", "제외", "배제", "제거", "없애", "지우",
                            "숨기", "거르", "걸러내",
                        }:
                            add(
                                index,
                                "COMMITTED",
                                "EXCLUDE",
                                "TYPED_DESIDERATIVE_EXCLUSION",
                                final_position,
                            )
                        elif any(
                            item in before for item in {"우선", "먼저", "선호"}
                        ):
                            add(
                                index,
                                "COMMITTED",
                                "PREFER",
                                "TYPED_DESIDERATIVE_PREFERENCE",
                                final_position,
                            )
                        elif compound_action in {
                            "고르", "선택", "구매", "사", "살", "받",
                        }:
                            add(
                                index,
                                "COMMITTED",
                                "PREFER" if has_strength_modifier else "MUST",
                                (
                                    "TYPED_STRENGTH_MODIFIED_DESIDERATIVE"
                                    if has_strength_modifier
                                    else "TYPED_DESIDERATIVE_SELECTION"
                                ),
                                final_position,
                            )

                if (
                    self.classifier.facet_strength_modifier
                    and token.form in {"좋", "낫"}
                ):
                    before = forms[max(0, index - 6):index]
                    if "쪽" in before or "더" in before:
                        add(
                            index,
                            "COMMITTED",
                            "PREFER",
                            "TYPED_COMPARATIVE_PREFERENCE",
                            final_position,
                        )

                if token.form == "하" and any(
                    item.tag == "EF"
                    and any(fragment in item.form for fragment in ("ᆯ게", "ㄹ게", "을게", "겠"))
                    for item in after_tokens
                ):
                    before_tokens = tokens[max(0, index - 5):index]
                    if any(
                        item.tag == "JKB" and item.form in {"로", "으로"}
                        for item in before_tokens
                    ):
                        add(
                            index,
                            "COMMITTED",
                            "MUST",
                            "TYPED_ROLE_PARTICLE_COMMITMENT",
                            final_position,
                        )

                if token.form == "하" and self.classifier.ep_ef_commitment_sequence:
                    before_tokens = tokens[max(0, index - 7):index]
                    if self.classifier.occurrence_predicate_proof:
                        has_role_particle = bool(
                            index > 0
                            and tokens[index - 1].tag == "JKB"
                            and tokens[index - 1].form in {"로", "으로"}
                        )
                    else:
                        has_role_particle = any(
                            item.tag == "JKB" and item.form in {"로", "으로"}
                            for item in before_tokens
                        )
                    final_endings = [item for item in after_tokens if item.tag == "EF"]
                    has_non_question_final = bool(final_endings) and not any(
                        "까" in item.form for item in final_endings
                    )
                    has_pre_final_commitment = any(
                        item.tag == "EP" and item.form == "겠"
                        for item in after_tokens
                    )
                    has_polite_request = any(
                        item.form == "주" and item.tag == "VX"
                        for item in after_tokens
                    ) and any(
                        item.form in {"세요", "십시오", "ᆸ시오", "으십시오"}
                        for item in final_endings
                    )
                    if has_role_particle and has_non_question_final and (
                        has_pre_final_commitment or has_polite_request
                    ):
                        polarity = (
                            "PREFER"
                            if any(
                                item.form in {"우선", "먼저", "선호"}
                                for item in before_tokens
                            )
                            else "MUST"
                        )
                        add(
                            index,
                            "COMMITTED",
                            polarity,
                            "TYPED_EP_EF_ROLE_COMMITMENT",
                            max(item.start + item.len for item in final_endings),
                        )

                if self.classifier.occurrence_predicate_proof:
                    immediately_role_bound = bool(
                        index > 0
                        and tokens[index - 1].tag == "JKB"
                        and tokens[index - 1].form in {"로", "으로"}
                    )
                    request_final = next(
                        (
                            item for item in after_tokens
                            if item.tag == "EF"
                            and item.form in {"세요", "십시오", "ᆸ시오", "으십시오"}
                        ),
                        None,
                    )
                    if (
                        token.form == "맞추"
                        and immediately_role_bound
                        and request_final is not None
                        and any(
                            item.form == "주" and item.tag == "VX"
                            for item in after_tokens
                        )
                    ):
                        add(
                            index,
                            "COMMITTED",
                            "MUST",
                            "TYPED_ROLE_BOUND_ALIGNMENT_REQUEST",
                            request_final.start + request_final.len,
                        )
                    if (
                        token.form == "하"
                        and immediately_role_bound
                        and any(
                            item.tag == "EC" and item.form in {"어야", "아야", "여야"}
                            for item in after_tokens
                        )
                    ):
                        obligation = next(
                            item for item in after_tokens
                            if item.tag == "EC" and item.form in {"어야", "아야", "여야"}
                        )
                        add(
                            index,
                            "COMMITTED",
                            "MUST",
                            "TYPED_ROLE_BOUND_OBLIGATION",
                            obligation.start + obligation.len,
                        )

            if token.form == "추천":
                after = forms[index + 1:min(len(forms), index + 8)]
                if "않" in after or "말" in after:
                    negative_position = max(
                        (
                            item.start + item.len
                            for item in tokens[index:min(len(tokens), index + 8)]
                            if item.form in {"않", "말"}
                        ),
                        default=token.start + token.len,
                    )
                    add(
                        index,
                        "COMMITTED",
                        "EXCLUDE",
                        "FRAME_NEGATED_RECOMMENDATION",
                        negative_position,
                    )

            if token.form == "없":
                before = forms[max(0, index - 8):index]
                purchase_absence = (
                    "생각" in before or "의사" in before
                ) and any(item in before for item in {"살", "사", "구매", "받"})
                not_needed = "필요" in before
                if purchase_absence or not_needed:
                    add(
                        index,
                        "COMMITTED",
                        "EXCLUDE",
                        "FRAME_NEGATED_ARGUMENT",
                        len(clause) + 1 if purchase_absence else None,
                    )

            if token.form in {"우대", "맨"}:
                add(index, "COMMITTED", "PREFER", "FRAME_RANK_POSITION")
            if token.form == "위" and "맨" in forms[max(0, index - 2):index]:
                add(index, "COMMITTED", "PREFER", "FRAME_RANK_POSITION")
            if (
                self.classifier.facet_predicate_ledger
                and token.form == "위"
                and any(
                    form in {"화면", "목록", "상단"}
                    for form in forms[max(0, index - 3):index]
                )
            ):
                add(index, "COMMITTED", "PREFER", "FRAME_RANK_POSITION")

            if self.classifier.referential_complement_temporal_resolution:
                after = forms[index + 1:min(len(forms), index + 9)]
                if token.form in {"포함", "선택"} and any(
                    form in {"않", "말"} for form in after
                ):
                    negative_end = max(
                        (
                            item.start + item.len
                            for item in tokens[index:min(len(tokens), index + 9)]
                            if item.form in {"않", "말"}
                        ),
                        default=token.start + token.len,
                    )
                    add(
                        index,
                        "COMMITTED",
                        "EXCLUDE",
                        "FRAME_NEGATED_SELECTION_FINAL",
                        negative_end + 1,
                    )

                if (
                    self.classifier.typed_reference_event_roles
                    and token.form == "넣"
                    and any(form in {"않", "말"} for form in after)
                ):
                    negative_end = max(
                        (
                            item.start + item.len
                            for item in tokens[index:min(len(tokens), index + 9)]
                            if item.form in {"않", "말"}
                        ),
                        default=token.start + token.len,
                    )
                    add(
                        index,
                        "COMMITTED",
                        "EXCLUDE",
                        "FRAME_NEGATED_INSERTION",
                        negative_end + 1,
                    )

                if self.classifier.typed_reference_event_roles and token.form == "없":
                    before = forms[max(0, index - 10):index]
                    if "의사" in before and any(
                        form in before for form in {"선택", "고르", "포함"}
                    ):
                        add(
                            index,
                            "COMMITTED",
                            "EXCLUDE",
                            "FRAME_NEGATED_SELECTION_INTENT",
                            token.start + token.len + 1,
                        )

        normalized = normalize(clause)
        for match in GENERIC_FACET_SELECTION_PATTERN.finditer(normalized):
            signals.append(PredicateSignal(
                start=match.start(),
                position=match.end(),
                modality="COMMITTED",
                polarity="MUST",
                marker=match.group(0),
                source="FRAME_GENERIC_SELECTION",
            ))

        temporal_forms = {"나중", "다음", "추후"}
        decision_forms = {"선택", "결정", "정하", "정", "확답", "답", "판단"}
        if self.classifier.referential_complement_temporal_resolution:
            decision_forms.update({"고르", "결론", "내"})
        temporal_indexes = [
            index for index, form in enumerate(forms) if form in temporal_forms
        ]
        for temporal_index in temporal_indexes:
            tail = forms[temporal_index:]
            if any(form in decision_forms for form in tail) or any(
                form in tail for form in {"하", "드리", "내리"}
            ):
                temporal_position = len(clause) + 2
                if self.classifier.typed_reference_event_roles:
                    decision_index = next(
                        (
                            index for index in range(temporal_index + 1, len(tokens))
                            if forms[index] in decision_forms
                            or forms[index] in {"하", "드리", "내리", "보"}
                        ),
                        temporal_index,
                    )
                    temporal_position = tokens[decision_index].start + tokens[decision_index].len + 2
                add(
                    temporal_index,
                    "TENTATIVE",
                    None,
                    "FRAME_FUTURE_DECISION",
                    temporal_position,
                )

        if re.search(r"(?:더|좀\s*더)[^.!?]{0,12}알아보[^.!?]{0,16}(?:정|결정)", normalized):
            signals.append(PredicateSignal(
                start=0,
                position=len(normalized) + 2,
                modality="TENTATIVE",
                polarity=None,
                marker="더 알아보고 결정",
                source="FRAME_FUTURE_DECISION",
            ))
        if re.search(r"(?:지금|당장)[^.!?]{0,12}(?:답|결정)[^.!?]{0,8}(?:안|어렵)", normalized):
            signals.append(PredicateSignal(
                start=0,
                position=len(normalized) + 2,
                modality="TENTATIVE",
                polarity=None,
                marker="현재 답변 유보",
                source="FRAME_FUTURE_DECISION",
            ))

        if self.classifier.typed_reference_event_roles:
            for match in re.finditer(
                r"(?:그|해당|이)\s*(?:형태|제형|성분|제품|횟수|조건)[^.!?]{0,16}"
                r"(?:안\s*(?:하|할)|하지\s*않)[^.!?]{0,12}(?:확정|결정|걸로)",
                normalized,
            ):
                signals.append(PredicateSignal(
                    start=match.start(),
                    position=match.end() + 1,
                    modality="COMMITTED",
                    polarity="EXCLUDE",
                    marker=match.group(0),
                    source="FRAME_NEGATED_COREFERENCE_ACTION",
                ))

            if self.classifier.facet_relation_events:
                for match in FACET_RELATION_NEGATED_STATE_PATTERN.finditer(normalized):
                    signals.append(PredicateSignal(
                        start=match.start(),
                        position=match.end(),
                        modality="COMMITTED",
                        polarity="EXCLUDE",
                        marker=match.group(0),
                        source="RELATION_NEGATED_STATE",
                    ))
                for match in FACET_RELATION_ELLIPTICAL_MUST_PATTERN.finditer(normalized):
                    signals.append(PredicateSignal(
                        start=match.start(),
                        position=match.end(),
                        modality="COMMITTED",
                        polarity="MUST",
                        marker=match.group(0),
                        source="RELATION_ELLIPTICAL_SELECTION",
                    ))

            typed_deferral = re.search(
                r"(?:며칠|주말|회의|검토|확인)[^.!?]{0,16}(?:뒤|후|끝나|지나)[^.!?]{0,20}"
                r"(?:결정|판단|정|답)|(?:조금|좀)\s*더[^.!?]{0,12}(?:살펴|보)[^.!?]{0,12}(?:정|결정)|"
                r"며칠[^.!?]{0,12}더\s*보[^.!?]{0,12}(?:정|결정|판단)",
                normalized,
            )
            if typed_deferral and not re.search(
                r"(?:지금|현재|바로|당장)", normalized[typed_deferral.end():]
            ):
                signals.append(PredicateSignal(
                    start=0,
                    position=len(normalized) + 3,
                    modality="TENTATIVE",
                    polarity=None,
                    marker="후속 판단 유보",
                    source="TYPED_TEMPORAL_DEFERRAL",
                ))

            if any(
                signal.polarity is not None
                and signal.source != "FRAME_GENERIC_SELECTION"
                for signal in signals
            ):
                signals = [
                    signal for signal in signals
                    if signal.source != "FRAME_GENERIC_SELECTION"
                ]

        if self.classifier.facet_predicate_ledger:
            # `먼저 확정하겠습니다` describes decision order, not
            # recommendation rank.  A bare temporal `먼저` must not override
            # an explicit `만 구매` MUST signal.
            if re.search(r"먼저[^.!?]{0,12}(?:확정|결정)", normalized):
                signals = [
                    signal
                    for signal in signals
                    if not (
                        signal.source == "MORPH_RANK_MARKER"
                        and normalize(signal.marker) == "먼저"
                    )
                ]

        if (
            self.classifier.facet_set_algebra
            and NON_CONSTRAINT_INQUIRY_PATTERN.search(normalized)
            and not re.search(
                r"(?:추천|순위|상단|가산점|우대)", normalized
            )
        ):
            signals = [signal for signal in signals if signal.polarity != "PREFER"]
        if (
            self.classifier.facet_set_algebra
            and FACET_RELATION_ELLIPTICAL_MUST_PATTERN.search(normalized)
        ):
            signals = [
                signal
                for signal in signals
                if not (
                    signal.source == "MORPH_INQUIRY_HEAD"
                    and normalize(signal.marker) in {"알리", "알"}
                )
            ]

        if self.classifier.typed_user_tail_modality:
            # `무조건 제외`, `반드시 빼`의 부사는 MUST 값 선택이 아니라
            # 뒤 EXCLUDE 행동의 강도를 높인다.
            exclusion_signals = [
                signal
                for signal in signals
                if signal.modality == "COMMITTED"
                and signal.polarity == "EXCLUDE"
            ]
            signals = [
                signal
                for signal in signals
                if not (
                    signal.source == "REGEX_MUST"
                    and normalize(signal.marker) in {"무조건", "반드시", "꼭", "필수"}
                    and any(
                        signal.position <= exclusion.start <= signal.position + 12
                        for exclusion in exclusion_signals
                    )
                )
            ]

        if self.classifier.ep_ef_commitment_sequence:
            for match in re.finditer(
                r"(?:우선(?:적으)?로|먼저|선호)[^.!?,]{0,12}"
                r"(?:할게요?|하겠습니다|해\s*주세요)",
                normalized,
            ):
                signals.append(PredicateSignal(
                    start=match.start(),
                    position=match.end(),
                    modality="COMMITTED",
                    polarity="PREFER",
                    marker=match.group(0),
                    source="TYPED_LOCAL_PREFERENCE_COMMITMENT",
                ))

        if self.classifier.facet_strength_modifier:
            strength_signals = [
                signal
                for signal in signals
                if signal.source == "TYPED_STRENGTH_MODIFIED_DESIDERATIVE"
            ]
            if strength_signals:
                last_strength = strength_signals[-1]
                signals = [
                    signal
                    for signal in signals
                    if not (
                        signal.source == "MORPH_SELECTION_HEAD"
                        and signal.position <= last_strength.position
                    )
                ]

        modality_order = {"COMMITTED": 0, "TENTATIVE": 1, "CANCELLED": 2}
        return tuple(sorted(signals, key=lambda item: (
            item.position,
            modality_order[item.modality],
        )))

    @staticmethod
    def _resolve_ordered_signals(
        signals: tuple[PredicateSignal, ...],
        classification_type: str,
        allow_untyped_commit: bool = False,
    ) -> tuple[str, str | None, bool]:
        if not signals:
            polarity = (
                classification_type
                if classification_type in {"MUST", "PREFER", "EXCLUDE"}
                else None
            )
            modality = "COMMITTED" if polarity is not None else "TENTATIVE"
            return modality, polarity, False

        latest_polarity: str | None = None
        final_modality = "TENTATIVE"
        final_polarity: str | None = None
        for signal in signals:
            if signal.polarity is not None:
                latest_polarity = signal.polarity
            final_modality = signal.modality
            final_polarity = signal.polarity or latest_polarity

        if final_modality == "COMMITTED" and final_polarity is None:
            if classification_type in {"MUST", "PREFER", "EXCLUDE"}:
                final_polarity = classification_type
            elif not allow_untyped_commit:
                final_modality = "TENTATIVE"
        return final_modality, final_polarity, True

    def _resolve_predicate_event(
        self,
        clause: str,
        classification_type: str,
    ) -> tuple[str, str | None, bool]:
        """Resolve the final signal while carrying the latest local polarity."""
        return self._resolve_ordered_signals(
            self._predicate_signals(clause),
            classification_type,
        )

    def _resolve_morphological_predicate_event(
        self,
        clause: str,
        classification_type: str,
    ) -> tuple[str, str | None, bool]:
        signals = self._morphological_predicate_signals(clause)
        allow_display_carry = bool(
            signals
            and signals[-1].source == "REGEX_DIRECT"
            and normalize(signals[-1].marker).startswith(("보여", "보이"))
        )
        return self._resolve_ordered_signals(
            signals,
            classification_type,
            allow_untyped_commit=allow_display_carry,
        )

    def _resolve_framed_predicate_event(
        self,
        clause: str,
        classification_type: str,
    ) -> tuple[str, str | None, bool]:
        signals = self._framed_predicate_signals(clause)
        allow_referential_commit = bool(
            self.classifier.referential_complement_temporal_resolution
            and signals
            and signals[-1].source == "REGEX_COMMIT"
            and all(signal.modality == "COMMITTED" for signal in signals)
        )
        return self._resolve_ordered_signals(
            signals,
            classification_type,
            allow_untyped_commit=allow_referential_commit,
        )

    def _unbound_facet_references(
        self,
        category_id: str,
        text: str,
    ) -> tuple[str, ...]:
        occurrences = self.matcher.occurrences(category_id, text)
        warnings = []
        for match in FACET_REFERENCE_PATTERN.finditer(text):
            facet_name = FACET_REFERENCE_NAMES[match.group(1)]
            has_antecedent = any(
                occurrence.facet.facet_name == facet_name
                and occurrence.end <= match.start()
                for occurrence in occurrences
            )
            if not has_antecedent:
                warnings.append(f"UNBOUND_FACET_REFERENCE:{match.group(0)}")
        return tuple(warnings)

    def _canonical_occurrences(self, category_id: str, text: str) -> tuple:
        """Collapse overlapping aliases for the same value to the longest span."""
        by_start_key = {}
        for item in self.matcher.occurrences(category_id, text):
            key = (item.start, item.facet.facet_name, item.facet.value_code)
            previous = by_start_key.get(key)
            if previous is None or item.end > previous.end:
                by_start_key[key] = item
        return tuple(sorted(
            by_start_key.values(), key=lambda item: (item.start, item.end)
        ))

    def _occurrence_strength_modifiers(
        self,
        category_id: str,
        text: str,
    ) -> tuple[StrengthModifier, ...]:
        """Bind an explicit strength marker to one nearby taxonomy occurrence."""
        if not self.classifier.occurrence_bound_strength_modifier:
            return ()
        occurrences = self._canonical_occurrences(category_id, text)
        if not occurrences:
            return ()

        modifiers: list[StrengthModifier] = []
        soft_pattern = (
            OCCURRENCE_SOFT_STRENGTH_PATTERN_V037
            if self.classifier.nearest_occurrence_strength_binding
            else OCCURRENCE_SOFT_STRENGTH_PATTERN
        )
        patterns = (
            (soft_pattern, "PREFER"),
            (OCCURRENCE_HARD_STRENGTH_PATTERN, "MUST"),
        )
        for pattern, strength in patterns:
            for match in pattern.finditer(text):
                if (
                    self.classifier.nearest_occurrence_strength_binding
                    and strength == "PREFER"
                    and match.group(0).startswith("되도록")
                    and match.start() > 0
                    and re.match(r"[0-9A-Za-z가-힣]", text[match.start() - 1])
                ):
                    # `포함되도록` contains the same character sequence.  A
                    # standalone modifier starts at a word boundary, whereas
                    # the predicate ending is attached to the preceding stem.
                    continue
                following = [
                    item
                    for item in occurrences
                    if 0 <= item.start - match.end() <= 20
                    and not re.search(r"[.!?]", text[match.end():item.start])
                ]
                preceding = [
                    item
                    for item in occurrences
                    if 0 <= match.start() - item.end <= 16
                    and not re.search(r"[.!?]", text[item.end:match.start()])
                ]
                if self.classifier.nearest_occurrence_strength_binding:
                    candidates = [
                        (item.start - match.end(), 0, item)
                        for item in following
                    ] + [
                        (match.start() - item.end, 1, item)
                        for item in preceding
                    ]
                    if not candidates:
                        continue
                    _, _, bound = min(
                        candidates,
                        key=lambda candidate: (
                            candidate[0], candidate[1], candidate[2].start
                        ),
                    )
                elif following:
                    bound = min(following, key=lambda item: (item.start, item.end))
                else:
                    if not preceding:
                        continue
                    bound = max(preceding, key=lambda item: (item.start, item.end))
                next_start = min(
                    (
                        item.start
                        for item in occurrences
                        if item.start > bound.start
                    ),
                    default=len(text),
                )
                modifiers.append(StrengthModifier(
                    start=match.start(),
                    end=match.end(),
                    strength=strength,
                    facet_name=bound.facet.facet_name,
                    value_code=bound.facet.value_code,
                    occurrence_span=(bound.start, bound.end),
                    scope_end=next_start,
                ))
        return tuple(sorted(modifiers, key=lambda item: (item.start, item.end)))

    @staticmethod
    def _tokens_through_ending(tokens: tuple, head_index: int, scope_end: int) -> int:
        """Return the end of the local auxiliary/ending chain after an action head."""
        end = tokens[head_index].start + tokens[head_index].len
        for token in tokens[head_index + 1:head_index + 9]:
            if token.start >= scope_end or token.tag in {"SF", "SP", "SS", "SSO", "SSC"}:
                break
            if token.tag.startswith(("E", "J")) or token.tag in {
                "VX", "VCP", "XSV", "XSA", "NNB",
            } or token.form in {"주", "드리", "하", "것", "이"}:
                end = token.start + token.len
                continue
            break
        return end

    def _typed_occurrence_action_evidence(
        self,
        category_id: str,
        text: str,
    ) -> tuple[ActionEvidence, ...]:
        """Build high-confidence action evidence without borrowing across occurrences."""
        if not self.classifier.typed_action_evidence:
            return ()
        occurrences = self._canonical_occurrences(category_id, text)
        if not occurrences:
            return ()
        tokens = tuple(self.kiwi.tokenize(text))
        modifiers = self._occurrence_strength_modifiers(category_id, text)
        evidence: list[ActionEvidence] = []

        removal_heads = {
            "빼", "제외", "배제", "제거", "없애", "지우", "숨기",
            "감추", "가리", "거르", "걸러내", "사절",
        }
        positive_heads = {
            "결정", "정하", "맞추", "보내", "구매", "주문", "선택",
            "고르", "골라내", "받", "사", "살", "주", "하",
        }
        unresolved_forms = {
            "고민", "망설", "미정", "보류", "문의", "궁금", "모르",
            "검토", "추측",
        }

        for occurrence in occurrences:
            later_starts = [
                item.start for item in occurrences if item.start >= occurrence.end
            ]
            scope_end = min(
                len(text),
                occurrence.end + 120,
                min(later_starts) if later_starts else len(text),
            )
            local_indexes = [
                index
                for index, token in enumerate(tokens)
                if token.start >= occurrence.end and token.start < scope_end
            ]
            if not local_indexes:
                continue
            local_forms = tuple(tokens[index].form for index in local_indexes)
            bound_modifiers = [
                item
                for item in modifiers
                if item.occurrence_span == (occurrence.start, occurrence.end)
            ]
            final_modifier = bound_modifiers[-1] if bound_modifiers else None

            def unresolved_after(position: int) -> bool:
                return any(
                    tokens[index].start >= position
                    and (
                        tokens[index].form in unresolved_forms
                        or any(
                            fragment in tokens[index].form
                            for fragment in ("을지", "ㄹ지", "ᆯ지", "을까", "ㄹ까", "ᆯ까")
                        )
                    )
                    for index in local_indexes
                )

            def append(
                head_index: int,
                predicate_end: int,
                action: str,
                polarity: str,
                source: str,
            ) -> None:
                evidence.append(ActionEvidence(
                    facet_name=occurrence.facet.facet_name,
                    value_code=occurrence.facet.value_code,
                    value=occurrence.facet.value,
                    taxonomy_span=(occurrence.start, occurrence.end),
                    predicate_span=(tokens[head_index].start, predicate_end),
                    action=action,
                    polarity=polarity,
                    source=source,
                    evidence_clause=text[occurrence.start:predicate_end].strip(),
                ))

            removal_index = next(
                (
                    index for index in local_indexes
                    if tokens[index].form in removal_heads
                ),
                None,
            )
            negated_removal_index = None
            if (
                self.classifier.typed_negated_removal_final_action
                and removal_index is not None
                and any(
                    tokens[index].form in {"않", "말"}
                    for index in local_indexes
                    if tokens[removal_index].start
                    < tokens[index].start
                    <= tokens[removal_index].start + 12
                )
            ):
                negated_removal_index = removal_index
                removal_index = None
            negated_action_index = next(
                (
                    local_indexes[offset + 1]
                    for offset in range(len(local_indexes) - 1)
                    if tokens[local_indexes[offset]].form == "안"
                    and tokens[local_indexes[offset + 1]].form == "하"
                ),
                None,
            )
            if removal_index is not None or negated_action_index is not None:
                head_index = (
                    removal_index if removal_index is not None else negated_action_index
                )
                assert head_index is not None
                predicate_end = self._tokens_through_ending(tokens, head_index, scope_end)
                softened = bool(
                    final_modifier is not None
                    and final_modifier.strength == "PREFER"
                )
                if not softened and not unresolved_after(tokens[head_index].start):
                    append(
                        head_index,
                        predicate_end,
                        "REMOVE",
                        "EXCLUDE",
                        (
                            "ACTION_NEGATED_CHOICE"
                            if removal_index is None
                            else "ACTION_NAMED_REMOVAL"
                        ),
                    )
                continue

            if self.classifier.typed_inclusion_action_evidence:
                inclusion_index = next(
                    (
                        index for index in local_indexes
                        if tokens[index].form in {"포함", "넣"}
                    ),
                    None,
                )
                if inclusion_index is not None:
                    following_indexes = [
                        index for index in local_indexes
                        if tokens[index].start > tokens[inclusion_index].start
                    ]
                    nominal_prohibition_index = next(
                        (
                            index
                            for index in following_indexes[:8]
                            if tokens[index].form == "금지"
                        ),
                        None,
                    )
                    negated_inclusion = any(
                        tokens[index].form
                        in (
                            {"않", "말", "금지"}
                            if self.classifier.nominal_inclusion_prohibition
                            else {"않", "말"}
                        )
                        for index in following_indexes[:8]
                    )
                    request_auxiliary = any(
                        tokens[index].form == "주"
                        for index in following_indexes
                    )
                    has_final = any(
                        tokens[index].tag == "EF"
                        for index in following_indexes
                    )
                    coordinated = bool(
                        self.classifier.coordinated_action_evidence
                        and request_auxiliary
                        and any(
                            tokens[index].tag == "EC"
                            and tokens[index].form in {"고", "되"}
                            for index in following_indexes
                        )
                    )
                    if (
                        (
                            has_final
                            or coordinated
                            or (
                                self.classifier.nominal_inclusion_prohibition_frame
                                and nominal_prohibition_index is not None
                            )
                        )
                        and not unresolved_after(tokens[inclusion_index].start)
                    ):
                        predicate_end = self._tokens_through_ending(
                            tokens, inclusion_index, scope_end
                        )
                        if self.classifier.nominal_inclusion_prohibition:
                            if nominal_prohibition_index is not None:
                                predicate_end = max(
                                    predicate_end,
                                    self._tokens_through_ending(
                                        tokens,
                                        nominal_prohibition_index,
                                        scope_end,
                                    ),
                                )
                        polarity = (
                            "EXCLUDE"
                            if negated_inclusion
                            else final_modifier.strength
                            if final_modifier is not None
                            else "MUST"
                        )
                        append(
                            inclusion_index,
                            predicate_end,
                            "REMOVE" if negated_inclusion else "SELECT",
                            polarity,
                            "ACTION_OCCURRENCE_BOUND_INCLUSION",
                        )
                        continue

            preference_index = next(
                (
                    index
                    for index in reversed(local_indexes)
                    if (
                        tokens[index].form in {"좋", "낫"}
                        and (
                            any(form in {"더", "쪽", "마음"} for form in local_forms)
                            or final_modifier is not None
                        )
                    )
                    or (
                        tokens[index].form == "들"
                        and "마음" in local_forms
                    )
                ),
                None,
            )
            if preference_index is not None:
                predicate_end = self._tokens_through_ending(
                    tokens, preference_index, scope_end
                )
                question = "?" in text[tokens[preference_index].start:scope_end]
                if not question and not unresolved_after(tokens[preference_index].start):
                    append(
                        preference_index,
                        predicate_end,
                        "RANK",
                        "PREFER",
                        "ACTION_RELATIONAL_PREFERENCE",
                    )
                    continue

            action_indexes = [
                index
                for index in local_indexes
                if tokens[index].form in positive_heads
            ]
            specific_action_indexes = [
                index
                for index in action_indexes
                if tokens[index].form not in {"하", "주"}
            ]
            if (
                self.classifier.typed_negated_removal_final_action
                and negated_removal_index is not None
                and not specific_action_indexes
            ):
                append(
                    negated_removal_index,
                    self._tokens_through_ending(
                        tokens, negated_removal_index, scope_end
                    ),
                    "REMOVE",
                    "EXCLUDE",
                    "ACTION_NAMED_REMOVAL",
                )
                continue
            if not action_indexes:
                continue
            if self.classifier.coordinated_action_evidence:
                head_index = (
                    specific_action_indexes[-1]
                    if specific_action_indexes
                    else action_indexes[-1]
                )
            else:
                head_index = action_indexes[-1]
            head = tokens[head_index]
            role_bound = any(
                tokens[index].tag == "JKB"
                and tokens[index].form in {"로", "으로", "에"}
                and occurrence.end <= tokens[index].start <= head.start
                for index in local_indexes
            )
            negated_removal_has_complement = bool(
                negated_removal_index is not None
                and any(
                    tokens[index].form in {"다른", "나머지", "외", "이외"}
                    for index in local_indexes
                    if tokens[negated_removal_index].start
                    < tokens[index].start
                    < head.start
                )
            )
            if (
                self.classifier.typed_negated_removal_final_action
                and negated_removal_has_complement
            ):
                continue
            if (
                self.classifier.typed_negated_removal_final_action
                and negated_removal_index is not None
                and tokens[negated_removal_index].start < head.start
                and head.form not in {"하", "주"}
            ):
                role_bound = True
            request_auxiliary = bool(
                head.form == "주"
                or any(
                    tokens[index].form == "주"
                    and tokens[index].start >= head.start
                    for index in local_indexes
                )
            )
            has_final = any(
                tokens[index].tag == "EF" and tokens[index].start >= head.start
                for index in local_indexes
            )
            has_polite_conditional = bool(
                request_auxiliary
                and any(
                    tokens[index].tag == "EC"
                    and tokens[index].form in {"면", "으면"}
                    and tokens[index].start >= head.start
                    for index in local_indexes
                )
            )
            has_coordinated_request = bool(
                self.classifier.coordinated_action_evidence
                and request_auxiliary
                and any(
                    tokens[index].tag == "EC"
                    and tokens[index].form in {"고", "되"}
                    and tokens[index].start >= head.start
                    for index in local_indexes
                )
            )
            question = "?" in text[head.start:scope_end]
            if question and not request_auxiliary:
                continue
            if not role_bound or not (
                has_final or has_polite_conditional or has_coordinated_request
            ):
                continue
            if unresolved_after(head.start):
                continue

            predicate_end = self._tokens_through_ending(tokens, head_index, scope_end)
            if has_polite_conditional:
                predicate_end = max(
                    predicate_end,
                    max(
                        tokens[index].start + tokens[index].len
                        for index in local_indexes
                        if tokens[index].tag == "EC"
                        and tokens[index].form in {"면", "으면"}
                    ),
                )
            ranking_evidence = bool(
                any(
                    form in {
                        "가산점", "우선", "우선순위", "먼저", "상단",
                        "상위", "위쪽", "선호",
                    }
                    for form in local_forms
                )
                or re.search(
                    r"(?:가산점|우선(?:적으)?로|우선순위|먼저|상단|상위|위쪽)",
                    text[occurrence.end:scope_end],
                )
            )
            polarity = (
                "PREFER"
                if ranking_evidence
                else final_modifier.strength
                if final_modifier is not None
                else "MUST"
            )
            append(
                head_index,
                predicate_end,
                "RANK" if polarity == "PREFER" else "SELECT",
                polarity,
                "ACTION_OCCURRENCE_BOUND_REQUEST",
            )

        return tuple(sorted(
            evidence,
            key=lambda item: (item.taxonomy_span[0], item.predicate_span[1]),
        ))

    def _negative_preference_evidence(
        self,
        category_id: str,
        text: str,
    ) -> tuple[NegativePreferenceEvidence, ...]:
        """Find a softened negative action bound to the final occurrence.

        The public constraint schema can express a positive preference and a
        hard exclusion, but not a preference *against* one value.  Such an
        event must therefore block every older fallback path instead of being
        coerced into either PREFER or EXCLUDE.
        """
        if not self.classifier.negative_preference_guard:
            return ()

        occurrences = self._canonical_occurrences(category_id, text)
        all_modifiers = self._occurrence_strength_modifiers(category_id, text)
        modifiers = tuple(
            item
            for item in all_modifiers
            if item.strength == "PREFER"
        )
        if not occurrences or not modifiers:
            return ()

        tokens = tuple(self.kiwi.tokenize(text))
        last_span_by_key: dict[tuple[str, int], tuple[int, int]] = {}
        for occurrence in occurrences:
            last_span_by_key[
                (occurrence.facet.facet_name, occurrence.facet.value_code)
            ] = (occurrence.start, occurrence.end)

        negative_heads = {
            "빼", "제외", "배제", "제거", "없애", "지우", "숨기",
            "감추", "가리", "거르", "걸러내", "사절", "빠지", "없",
        }
        if self.classifier.expanded_negative_preference_relation:
            negative_heads.update({"피", "피하", "아니", "말", "않"})
        if self.classifier.expanded_negative_state_predicates:
            negative_heads.add("꺼리")
        evidence: list[NegativePreferenceEvidence] = []

        for modifier in modifiers:
            key = (modifier.facet_name, modifier.value_code)
            occurrence = next(
                item
                for item in occurrences
                if (item.start, item.end) == modifier.occurrence_span
                and (item.facet.facet_name, item.facet.value_code) == key
            )
            carried_state = False
            if modifier.occurrence_span != last_span_by_key.get(key):
                if not self.classifier.negative_preference_state_carry:
                    continue
                final_span = last_span_by_key[key]
                final_occurrence = next(
                    item
                    for item in occurrences
                    if (item.start, item.end) == final_span
                    and (item.facet.facet_name, item.facet.value_code) == key
                )
                final_scope_end = min(
                    (
                        item.start
                        for item in occurrences
                        if item.start > final_occurrence.start
                    ),
                    default=len(text),
                )
                final_indexes = [
                    index
                    for index, token in enumerate(tokens)
                    if final_occurrence.end <= token.start < final_scope_end
                ]
                final_forms = {tokens[index].form for index in final_indexes}
                has_negative_state = bool(
                    final_forms & negative_heads
                    or (
                        self.classifier.expanded_negative_state_predicates
                        and "별로" in final_forms
                    )
                    or any(
                        final_indexes[offset + 1] in final_indexes
                        and tokens[final_indexes[offset]].form == "안"
                        and tokens[final_indexes[offset + 1]].form
                        in (
                            {"하", "선택", "고르", "사", "구매", "들어가", "포함"}
                            if self.classifier.expanded_negative_state_predicates
                            else {"하", "선택", "고르", "사", "구매"}
                        )
                        for offset in range(len(final_indexes) - 1)
                    )
                )
                has_weak_state = bool(
                    final_forms
                    & {"싶", "좀", "편", "마음", "상태", "고려", "별로"}
                    or re.search(
                        r"(?:선호[^.!?]{0,8}않|고려\s*중|생각\s*중)",
                        text[final_occurrence.end:final_scope_end],
                    )
                )
                final_has_hard_modifier = any(
                    item.strength == "MUST"
                    and item.occurrence_span == final_span
                    for item in all_modifiers
                )
                if not (
                    has_negative_state
                    and has_weak_state
                    and not final_has_hard_modifier
                ):
                    continue
                carried_state = True
            local_indexes = [
                index
                for index, token in enumerate(tokens)
                if occurrence.end <= token.start < modifier.scope_end
            ]
            if not local_indexes:
                continue

            head_index = next(
                (
                    index
                    for index in local_indexes
                    if tokens[index].form in negative_heads
                ),
                None,
            )
            source = "SOFTENED_REMOVAL"
            if head_index is None:
                negated_heads = (
                    {"하", "선택", "고르", "사", "구매", "들어가", "포함"}
                    if self.classifier.expanded_negative_state_predicates
                    else {"하", "선택", "고르", "사", "구매"}
                )
                head_index = next(
                    (
                        local_indexes[offset + 1]
                        for offset in range(len(local_indexes) - 1)
                        if tokens[local_indexes[offset]].form == "안"
                        and tokens[local_indexes[offset + 1]].form
                        in negated_heads
                    ),
                    None,
                )
                source = "SOFTENED_NEGATED_SELECTION"
            if head_index is None:
                continue

            head = tokens[head_index]
            argument_text = normalize(text[occurrence.end:head.start])
            complement_pattern = (
                r"(?:외|이외)(?:에는|은|는|을|를)?$"
                if self.classifier.expanded_negative_preference_relation
                else r"(?:외|이외|아닌)(?:에는|은|는|을|를)?$"
            )
            if re.search(complement_pattern, argument_text):
                continue

            following = [
                tokens[index]
                for index in local_indexes
                if head.start < tokens[index].start <= head.start + 10
            ]
            # `빼지 말고 포함해 줘` negates the removal itself and is a
            # positive request, not a negative preference.
            if any(token.form == "말" for token in following) or any(
                token.form == "않" for token in following
            ):
                continue

            predicate_end = self._tokens_through_ending(
                tokens, head_index, modifier.scope_end
            )
            evidence.append(NegativePreferenceEvidence(
                facet_name=occurrence.facet.facet_name,
                value_code=occurrence.facet.value_code,
                value=occurrence.facet.value,
                taxonomy_span=(occurrence.start, occurrence.end),
                modifier_span=(modifier.start, modifier.end),
                predicate_span=(head.start, predicate_end),
                source=(
                    f"{source}_STATE_CARRY" if carried_state else source
                ),
            ))

        return tuple(sorted(
            evidence,
            key=lambda item: (item.taxonomy_span[0], item.predicate_span[1]),
        ))

    def _ambiguous_negated_removal_targets(
        self,
        category_id: str,
        text: str,
    ) -> tuple[tuple[str, int], ...]:
        """Find a negated removal whose later action targets alternatives.

        `X를 빼지 말고 X를 꼭 포함` has a typed positive proof for X and is
        safe.  In `X를 빼지 말고 다른/나머지를 골라`, however, neither the
        removal marker nor the alternative-selection shell proves X's final
        polarity.  The current schema cannot encode that unresolved relation.
        """
        if not self.classifier.ambiguous_negated_removal_target_guard:
            return ()

        occurrences = self._canonical_occurrences(category_id, text)
        if not occurrences:
            return ()
        hard_positive = {
            (item.facet_name, item.value_code)
            for item in self._typed_occurrence_action_evidence(category_id, text)
            if item.action != "REMOVE" and item.polarity == "MUST"
        }
        normalized = normalize(text)
        removal = re.compile(
            r"(?:빼|제외|배제|제거)[^.!?]{0,10}지[^.!?]{0,8}"
            + (
                r"(?:않|말|마)"
                if self.classifier.expanded_ambiguous_negative_target_forms
                else r"(?:않|말)"
            )
        )
        alternative = re.compile(r"(?:다른|나머지|그\s*외|그외|외에)")
        action = re.compile(
            r"(?:고르|골|선택|추리|추려|찾|봐|보|담|고려"
            + (
                r"|살펴|훑|둘러|검토|확인"
                if self.classifier.expanded_ambiguous_negative_target_forms
                else ""
            )
            + (
                r"|따지|따져"
                if self.classifier.expanded_alternative_deliberation_action
                else ""
            )
            + r")"
        )
        keys: set[tuple[str, int]] = set()
        for occurrence in occurrences:
            key = (occurrence.facet.facet_name, occurrence.facet.value_code)
            if key in hard_positive:
                continue
            tail = normalized[occurrence.end:]
            match = removal.search(tail)
            if match is None or match.start() > 16:
                continue
            following = tail[match.end():]
            alternative_match = alternative.search(following)
            if alternative_match is None:
                continue
            if action.search(following[alternative_match.start():]) is None:
                continue
            keys.add(key)
        return tuple(sorted(keys))

    def _negative_comparative_state_targets(
        self,
        category_id: str,
        text: str,
    ) -> tuple[tuple[str, int], ...]:
        """Find softened `X 안 들어간/안 되는 쪽이 좋다` states.

        The surface `좋다` is positive, but its argument is the complement of
        X.  Until negative preferences have their own schema type this must be
        REVIEW rather than a positive PREFER for X.
        """
        if not self.classifier.negative_comparative_state_guard:
            return ()

        occurrences = self._canonical_occurrences(category_id, text)
        soft_keys = {
            (item.facet_name, item.value_code)
            for item in self._occurrence_strength_modifiers(category_id, text)
            if item.strength == "PREFER"
        }
        hard_positive_keys = {
            (item.facet_name, item.value_code)
            for item in self._typed_occurrence_action_evidence(category_id, text)
            if item.action != "REMOVE" and item.polarity == "MUST"
        }
        if self.classifier.explicit_final_hard_positive_termination:
            last_occurrence_by_key = {
                (item.facet.facet_name, item.facet.value_code): item
                for item in occurrences
            }
            hard_action = re.compile(
                r"(?:꼭|반드시|무조건)[^.!?]{0,24}"
                r"(?:포함|선택|고르|골라|넣|구매|주문)"
                r"|(?:포함|선택|고르|골라|넣|구매|주문)[^.!?]{0,24}"
                r"(?:꼭|반드시|무조건)"
            )
            for key, occurrence in last_occurrence_by_key.items():
                tail = normalize(text[occurrence.start:])
                match = hard_action.search(tail)
                if match is not None and not re.search(
                    r"(?:하지|않|말|금지)", match.group(0)
                ):
                    hard_positive_keys.add(key)
        if not occurrences or not soft_keys:
            return ()

        tokens = tuple(self.kiwi.tokenize(text))
        keys: set[tuple[str, int]] = set()
        for offset, occurrence in enumerate(occurrences):
            key = (occurrence.facet.facet_name, occurrence.facet.value_code)
            if key not in soft_keys or key in hard_positive_keys:
                continue
            scope_end = (
                occurrences[offset + 1].start
                if offset + 1 < len(occurrences)
                else len(text)
            )
            local = [
                index
                for index, token in enumerate(tokens)
                if occurrence.end <= token.start < scope_end
            ]
            for position, index in enumerate(local):
                if tokens[index].form != "안":
                    continue
                predicate = next(
                    (
                        following
                        for following in local[position + 1:position + 5]
                        if tokens[following].form in {"들어가", "포함", "되"}
                    ),
                    None,
                )
                if predicate is None:
                    continue
                later = [
                    following
                    for following in local
                    if tokens[following].start > tokens[predicate].start
                ]
                relation_position = next(
                    (
                        pos
                        for pos, following in enumerate(later[:8])
                        if tokens[following].form in {"쪽", "것", "제품"}
                    ),
                    None,
                )
                if relation_position is None:
                    continue
                if any(
                    tokens[following].form in {"좋", "낫"}
                    for following in later[relation_position + 1:relation_position + 7]
                ):
                    keys.add(key)
                    break
        return tuple(sorted(keys))

    def _apply_typed_occurrence_evidence(
        self,
        category_id: str,
        text: str,
        baseline: ExtractionResult,
    ) -> ExtractionResult:
        if not self.classifier.typed_action_evidence:
            return baseline
        occurrences = self._canonical_occurrences(category_id, text)
        action_evidence = self._typed_occurrence_action_evidence(category_id, text)
        if not occurrences or not action_evidence:
            return baseline

        last_span_by_key: dict[tuple[str, int], tuple[int, int]] = {}
        first_position: dict[tuple[str, int], int] = {}
        for occurrence in occurrences:
            key = (occurrence.facet.facet_name, occurrence.facet.value_code)
            last_span_by_key[key] = (occurrence.start, occurrence.end)
            first_position.setdefault(key, occurrence.start)
        final_evidence: dict[tuple[str, int], ActionEvidence] = {}
        for item in action_evidence:
            key = (item.facet_name, item.value_code)
            if item.taxonomy_span != last_span_by_key.get(key):
                continue
            previous = final_evidence.get(key)
            if previous is None or item.predicate_span[1] > previous.predicate_span[1]:
                final_evidence[key] = item

        if baseline.status == "PARSED":
            rewritten = []
            for constraint in baseline.constraints:
                key = (constraint.facet_name, constraint.value_code)
                item = final_evidence.get(key)
                if item is None:
                    rewritten.append(constraint)
                    continue
                rewritten.append(replace(
                    constraint,
                    constraint_type=item.polarity,
                    evidence_clause=item.evidence_clause,
                    proof=None,
                ))
            return replace(baseline, constraints=tuple(rewritten))

        expected_keys = set(last_span_by_key)
        if set(final_evidence) != expected_keys:
            return baseline
        constraints = tuple(
            FacetConstraint(
                facet_name=final_evidence[key].facet_name,
                value_code=final_evidence[key].value_code,
                value=final_evidence[key].value,
                constraint_type=final_evidence[key].polarity,
                evidence_clause=final_evidence[key].evidence_clause,
            )
            for key in sorted(expected_keys, key=lambda item: first_position[item])
        )
        return ExtractionResult("PARSED", constraints, (), (text,))

    @staticmethod
    def _non_committed_frame_matches(text: str) -> tuple[re.Match[str], ...]:
        """Return cancellation, deferral, and non-user stance candidates.

        Predicate frames are deliberately conservative: a later explicit current
        decision can supersede an earlier unresolved frame, but a generic request
        such as `취소해줘` is the cancellation action itself, not restoration.
        """
        value = normalize(text)
        matches = [
            match
            for pattern in PREDICATE_FRAME_NON_COMMITTED_PATTERNS
            if (match := pattern.search(value)) is not None
        ]
        return tuple(sorted(matches, key=lambda item: item.end(), reverse=True))

    def _build_predicate_frames(
        self,
        category_id: str,
        text: str,
    ) -> tuple[PredicateFrame, ...]:
        """Bind a predicate to an explicit named value or its complement.

        This layer only emits high-confidence frames.  It never borrows a rank,
        removal, or question marker from an unrelated metadata argument.  When it
        cannot cover every named taxonomy value, the established event ledger is
        allowed to decide instead.
        """
        occurrences = self.matcher.occurrences(category_id, text)
        frames: list[PredicateFrame] = []
        for occurrence in occurrences:
            facet = occurrence.facet
            # Keep the binding local enough that a later, separately named facet
            # cannot donate its predicate to this occurrence.
            next_other_start = min(
                (
                    other.start
                    for other in occurrences
                    if other.start > occurrence.start
                    and (
                        other.facet.facet_name,
                        other.facet.value_code,
                    ) != (facet.facet_name, facet.value_code)
                ),
                default=len(text),
            )
            local_end = min(len(text), next_other_start, occurrence.end + 96)
            after_raw = text[occurrence.end:local_end]
            after = normalize(after_raw)
            before = normalize(text[max(0, occurrence.start - 32):occurrence.start])

            relation = next(
                (
                    match
                    for match in PREDICATE_FRAME_RELATION_PATTERN.finditer(after)
                    if not (
                        match.group(0) == "말고"
                        and after[max(0, match.start() - 3):match.start()].rstrip().endswith("지")
                    )
                ),
                None,
            )
            if relation and relation.start() <= 56:
                relation_tail = after[relation.start():]
                remove = PREDICATE_FRAME_REMOVE_ACTION_PATTERN.search(relation_tail)
                select = PREDICATE_FRAME_SELECT_ACTION_PATTERN.search(relation_tail)
                candidate_pool = PREDICATE_FRAME_COMPLEMENT_POOL_PATTERN.search(
                    relation_tail
                )
                # Removal of the complement keeps only the named anchor. Positive
                # selection of the complement excludes the named anchor.
                if remove is not None and (
                    select is None or remove.start() <= select.start()
                ):
                    action, polarity = "REMOVE", "MUST"
                    action_end = relation.start() + remove.end()
                elif select is not None or candidate_pool is not None:
                    action, polarity = "SELECT", "EXCLUDE"
                    selected_span = select or candidate_pool
                    action_end = relation.start() + selected_span.end()
                else:
                    action = polarity = ""
                    action_end = 0
                if polarity:
                    frames.append(PredicateFrame(
                        facet_name=facet.facet_name,
                        value_code=facet.value_code,
                        value=facet.value,
                        action=action,
                        target_role="COMPLEMENT_OF",
                        argument_start=occurrence.start,
                        argument_end=min(local_end, occurrence.end + action_end),
                        modality="COMMITTED",
                        temporal="NOW",
                        negated="아니" in relation.group(0),
                        polarity=polarity,
                        evidence_clause=text[occurrence.start:min(local_end, occurrence.end + action_end)].strip(),
                    ))
                    continue

            if re.search(r"(?:반드시|무조건|필수|오직)[^.!?]{0,14}$", before):
                frames.append(PredicateFrame(
                    facet_name=facet.facet_name,
                    value_code=facet.value_code,
                    value=facet.value,
                    action="SELECT",
                    target_role="NAMED_VALUE",
                    argument_start=occurrence.start,
                    argument_end=occurrence.end,
                    modality="COMMITTED",
                    temporal="NOW",
                    negated=False,
                    polarity="MUST",
                    evidence_clause=text[max(0, occurrence.start - 32):occurrence.end].strip(),
                ))
                continue

            if self.classifier.occurrence_predicate_proof:
                negated_selection = OCCURRENCE_NAMED_NEGATED_SELECTION_PATTERN.search(after)
                if negated_selection is not None:
                    frames.append(PredicateFrame(
                        facet_name=facet.facet_name,
                        value_code=facet.value_code,
                        value=facet.value,
                        action="REMOVE",
                        target_role="NAMED_VALUE",
                        argument_start=occurrence.start,
                        argument_end=occurrence.end + negated_selection.end(),
                        modality="COMMITTED",
                        temporal="NOW",
                        negated=False,
                        polarity="EXCLUDE",
                        evidence_clause=text[
                            occurrence.start:occurrence.end + negated_selection.end()
                        ].strip(),
                    ))
                    continue

            must = PREDICATE_FRAME_NAMED_MUST_PATTERN.search(after)
            if must is not None:
                frames.append(PredicateFrame(
                    facet_name=facet.facet_name,
                    value_code=facet.value_code,
                    value=facet.value,
                    action="SELECT",
                    target_role="NAMED_VALUE",
                    argument_start=occurrence.start,
                    argument_end=occurrence.end + must.end(),
                    modality="COMMITTED",
                    temporal="NOW",
                    negated=False,
                    polarity="MUST",
                    evidence_clause=text[occurrence.start:occurrence.end + must.end()].strip(),
                ))
                continue

            excluded = PREDICATE_FRAME_NAMED_EXCLUDE_PATTERN.search(after)
            if excluded is not None:
                frames.append(PredicateFrame(
                    facet_name=facet.facet_name,
                    value_code=facet.value_code,
                    value=facet.value,
                    action="REMOVE",
                    target_role="NAMED_VALUE",
                    argument_start=occurrence.start,
                    argument_end=occurrence.end + excluded.end(),
                    modality="COMMITTED",
                    temporal="NOW",
                    negated=False,
                    polarity="EXCLUDE",
                    evidence_clause=text[occurrence.start:occurrence.end + excluded.end()].strip(),
                ))
                continue
        return tuple(frames)

    def _extract_with_predicate_frames(
        self,
        category_id: str,
        text: str,
    ) -> ExtractionResult | None:
        occurrences = self.matcher.occurrences(category_id, text)
        if not occurrences:
            return None

        normalized = normalize(text)
        for unresolved in self._non_committed_frame_matches(text):
            tail = normalized[unresolved.end():]
            strong_boundaries = tuple(
                match.end()
                for match in re.finditer(r"[.!?]", normalized[:unresolved.start()])
            )
            segment_start = strong_boundaries[-1] if strong_boundaries else 0
            cancellation = bool(
                re.search(r"(?:취소|철회|없던\s*걸|보류)", unresolved.group(0))
            )
            unresolved_owns_taxonomy = any(
                (
                    segment_start <= occurrence.start < unresolved.end()
                    or (cancellation and occurrence.start < unresolved.start())
                )
                for occurrence in occurrences
            )
            if unresolved_owns_taxonomy and not TYPED_CURRENT_OVERRIDE_PATTERN.search(tail):
                return ExtractionResult(
                    "REVIEW",
                    (),
                    ("PREDICATE_FRAME_NON_COMMITTED",),
                    (text,),
                )

        frames = self._build_predicate_frames(category_id, text)
        expected_keys = {
            (item.facet.facet_name, item.facet.value_code) for item in occurrences
        }
        frames_by_key: dict[tuple[str, int], list[PredicateFrame]] = {}
        for frame in frames:
            frames_by_key.setdefault((frame.facet_name, frame.value_code), []).append(frame)
        has_relation_frame = any(
            frame.target_role == "COMPLEMENT_OF" for frame in frames
        )
        has_metadata_distractor = bool(
            NON_CONSTRAINT_INQUIRY_PATTERN.search(normalize(text))
        )
        if not has_relation_frame and not has_metadata_distractor:
            return None
        if set(frames_by_key) != expected_keys:
            return None

        selected: list[PredicateFrame] = []
        for key in expected_keys:
            candidates = frames_by_key[key]
            polarities = {item.polarity for item in candidates}
            if len(polarities) != 1:
                return ExtractionResult(
                    "REVIEW",
                    (),
                    (f"PREDICATE_FRAME_POLARITY_CONFLICT:{key[0]}:{key[1]}",),
                    (text,),
                )
            selected.append(max(candidates, key=lambda item: item.argument_end))

        selected.sort(key=lambda item: item.argument_start)
        constraints = tuple(
            FacetConstraint(
                facet_name=frame.facet_name,
                value_code=frame.value_code,
                value=frame.value,
                constraint_type=frame.polarity,
                evidence_clause=frame.evidence_clause,
            )
            for frame in selected
        )
        return ExtractionResult("PARSED", constraints, (), (text,))

    @staticmethod
    def _frame_has_current_marker(text: str, frame: PredicateFrame, start: int = 0) -> bool:
        value = normalize(text)
        window_start = max(start, frame.argument_start - 24)
        window_end = min(len(value), frame.argument_start + 8)
        return bool(PREDICATE_FRAME_CURRENT_MARKER_PATTERN.search(
            value[window_start:window_end]
        ))

    def _non_committed_frame_keys(
        self,
        category_id: str,
        text: str,
    ) -> tuple[tuple[re.Match[str], set[tuple[str, int]]], ...]:
        """Bind unresolved discourse operators to taxonomy keys in their span."""
        normalized = normalize(text)
        occurrences = self.matcher.occurrences(category_id, text)
        bound = []
        for match in self._non_committed_frame_matches(text):
            boundaries = tuple(
                item.end()
                for item in re.finditer(r"[.!?]", normalized[:match.start()])
            )
            segment_start = boundaries[-1] if boundaries else 0
            cancellation = bool(
                re.search(r"(?:취소|철회|없던\s*걸|보류)", match.group(0))
            )
            keys = {
                (item.facet.facet_name, item.facet.value_code)
                for item in occurrences
                if (
                    segment_start <= item.start < match.end()
                    or (cancellation and item.start < match.start())
                )
            }
            if keys:
                bound.append((match, keys))
        return tuple(bound)

    def _extract_with_unified_predicate_frame_ledger(
        self,
        category_id: str,
        text: str,
    ) -> ExtractionResult:
        """Resolve one final per-facet ledger from legacy and explicit frames.

        The mature event extractor supplies frames for ordinary predicates.  The
        explicit span builder supplies complement and metadata ownership.  Both
        feed this single final ledger; no second extractor is selected as a
        sentence-level fallback.
        """
        occurrences = self.matcher.occurrences(category_id, text)
        baseline = self._extract_with_predicate_event_ordering(category_id, text)
        if not occurrences:
            return baseline

        frames = self._build_predicate_frames(category_id, text)
        frames_by_key: dict[tuple[str, int], list[PredicateFrame]] = {}
        for frame in frames:
            frames_by_key.setdefault((frame.facet_name, frame.value_code), []).append(frame)
        for candidates in frames_by_key.values():
            candidates.sort(key=lambda item: (item.argument_start, item.argument_end))

        baseline_keys = {
            (item.facet_name, item.value_code) for item in baseline.constraints
        }

        unresolved_keys: set[tuple[str, int]] = set()
        for match, keys in self._non_committed_frame_keys(category_id, text):
            for key in keys:
                restored = any(
                    frame.argument_start >= match.start()
                    and self._frame_has_current_marker(text, frame, match.start())
                    for frame in frames_by_key.get(key, ())
                )
                if (
                    not restored
                    and key in baseline_keys
                ):
                    current = PREDICATE_FRAME_CURRENT_MARKER_PATTERN.search(
                        normalize(text)[match.start():]
                    )
                    if current is not None:
                        current_start = match.start() + current.start()
                        occurrence_keys = {
                            (item.facet.facet_name, item.facet.value_code)
                            for item in self.matcher.occurrences(category_id, text)
                        }
                        repeated_near_current = any(
                            (item.facet.facet_name, item.facet.value_code) == key
                            and item.start >= match.start()
                            and abs(item.start - current_start) <= 20
                            for item in self.matcher.occurrences(category_id, text)
                        )
                        current_tail = normalize(text)[current_start:]
                        referential_current = bool(
                            re.search(
                                r"(?:그|해당)\s*(?:성분|제형|형태|횟수|조건)|그렇게|그대로",
                                current_tail,
                            )
                        )
                        restored = bool(
                            repeated_near_current
                            or referential_current
                            or len(occurrence_keys) == 1
                        )
                if not restored:
                    unresolved_keys.add(key)
        if unresolved_keys:
            labels = ",".join(f"{facet}:{code}" for facet, code in sorted(unresolved_keys))
            return ExtractionResult(
                "REVIEW",
                (),
                (f"UNIFIED_FRAME_UNRESOLVED:{labels}",),
                (text,),
            )

        ledger: dict[tuple[str, int], FacetConstraint] = {
            (item.facet_name, item.value_code): item for item in baseline.constraints
        }
        metadata = bool(NON_CONSTRAINT_INQUIRY_PATTERN.search(normalize(text)))
        has_complement_frame = any(
            frame.target_role == "COMPLEMENT_OF" for frame in frames
        )
        if baseline.status == "REVIEW" and not has_complement_frame:
            return baseline
        for key, candidates in frames_by_key.items():
            explicit = [
                frame for frame in candidates
                if frame.target_role == "COMPLEMENT_OF"
                or metadata
                or self._frame_has_current_marker(text, frame)
            ]
            if self.classifier.occurrence_predicate_proof:
                final_named_frames = [
                    frame
                    for frame in candidates
                    if frame.target_role == "NAMED_VALUE"
                    and frame.action == "REMOVE"
                    and not any(
                        occurrence.start > frame.argument_end
                        and (
                            occurrence.facet.facet_name,
                            occurrence.facet.value_code,
                        ) == key
                        for occurrence in occurrences
                    )
                ]
                explicit.extend(
                    frame for frame in final_named_frames if frame not in explicit
                )
            if not explicit and baseline.status != "PARSED":
                explicit = candidates
            if not explicit:
                continue
            chosen = explicit[-1]
            ledger[key] = FacetConstraint(
                facet_name=chosen.facet_name,
                value_code=chosen.value_code,
                value=chosen.value,
                constraint_type=chosen.polarity,
                evidence_clause=chosen.evidence_clause,
            )

        expected_keys = {
            (item.facet.facet_name, item.facet.value_code) for item in occurrences
        }
        if set(ledger) != expected_keys:
            return baseline if baseline.status == "REVIEW" else ExtractionResult(
                "REVIEW",
                (),
                tuple(
                    f"UNIFIED_FRAME_MISSING:{facet}:{code}"
                    for facet, code in sorted(expected_keys - set(ledger))
                ),
                (text,),
            )

        first_position = {
            key: min(
                item.start
                for item in occurrences
                if (item.facet.facet_name, item.facet.value_code) == key
            )
            for key in expected_keys
        }
        constraints = tuple(
            ledger[key] for key in sorted(ledger, key=lambda item: first_position[item])
        )
        return ExtractionResult("PARSED", constraints, (), (text,))

    def _extract_with_predicate_event_ordering(
        self,
        category_id: str,
        text: str,
    ) -> ExtractionResult:
        """Resolve facet state from the last predicate signal, even within a clause."""
        normalized = normalize(text)
        if self.classifier.morphological_predicate_events:
            unbound = self._unbound_facet_references(category_id, text)
            if unbound:
                return ExtractionResult("REVIEW", (), unbound, (text,))
        if self.classifier.typed_reference_event_roles:
            final_unresolved = TYPED_FINAL_UNRESOLVED_PATTERN.search(normalized)
            if final_unresolved and not TYPED_CURRENT_OVERRIDE_PATTERN.search(
                normalized[final_unresolved.start():]
            ):
                return ExtractionResult(
                    "REVIEW", (), ("TYPED_FINAL_STATE_UNRESOLVED",), (text,)
                )
            deferred = (
                TYPED_GLOBAL_DEFERRAL_PATTERN.search(normalized)
                or TYPED_TEMPORAL_TOKEN_DEFERRAL_PATTERN.search(normalized)
            )
            if deferred:
                tail = normalized[deferred.end():]
                has_unresolved_tail = TYPED_UNRESOLVED_TAIL_PATTERN.search(tail)
                has_current_override = TYPED_CURRENT_OVERRIDE_PATTERN.search(tail)
                if (
                    self.classifier.facet_predicate_ledger
                    and has_current_override
                    and self._has_cross_facet_temporal_override(
                        category_id, text, deferred.start(), deferred.end()
                    )
                ):
                    return ExtractionResult(
                        "REVIEW", (), ("FACET_TEMPORAL_CONFLICT",), (text,)
                    )
                if has_unresolved_tail or not has_current_override:
                    return ExtractionResult(
                        "REVIEW", (), ("TYPED_TEMPORAL_DEFERRAL",), (text,)
                    )
        if any(pattern in normalized for pattern in ALTERNATIVE_PATTERNS):
            return ExtractionResult("REVIEW", (), ("ALTERNATIVE_VALUE_SCOPE",), (text,))
        if "아니면" in normalized and not self.classifier.is_positive_double_negative(normalized):
            return ExtractionResult("REVIEW", (), ("ALTERNATIVE_VALUE_SCOPE",), (text,))

        base_clauses = self.split_clauses(category_id, text)
        explicitly_split = tuple(
            expanded
            for clause in base_clauses
            for expanded in self._split_explicit_multi_value_clause(category_id, clause)
        )
        clauses = tuple(
            scoped
            for clause in explicitly_split
            for scoped in self._split_candidate_pool_scope(category_id, clause)
        )
        if self.classifier.facet_predicate_ledger:
            clauses = tuple(
                local
                for clause in clauses
                for local in self._split_facet_predicate_ledger_clause(
                    category_id, clause
                )
            )
        events: list[FacetEvent] = []
        facets_by_key = {}
        last_targets: tuple[tuple[str, int], ...] = ()

        for order, clause in enumerate(clauses):
            facet_result = self.matcher.match(category_id, clause)
            if facet_result.warnings:
                return ExtractionResult(
                    "REVIEW",
                    (),
                    tuple(f"{warning}: {clause}" for warning in facet_result.warnings),
                    clauses,
                )
            explicit_targets = tuple(
                (facet.facet_name, facet.value_code) for facet in facet_result.facets
            )
            for facet in facet_result.facets:
                facets_by_key[(facet.facet_name, facet.value_code)] = facet

            classification = self.classifier.classify(
                clause,
                tuple(facet.value for facet in facet_result.facets),
            )
            if self.classifier.predicate_argument_temporal_scope:
                resolver = self._resolve_framed_predicate_event
            elif self.classifier.morphological_predicate_events:
                resolver = self._resolve_morphological_predicate_event
            else:
                resolver = self._resolve_predicate_event
            modality, polarity, has_predicate_signal = resolver(
                clause, classification.constraint_type
            )

            targets = explicit_targets
            target_role = "NAMED_VALUE"
            derived_anchor_polarity: str | None = None
            if (
                self.classifier.facet_predicate_ledger
                and explicit_targets
                and (
                    self._is_facet_relation_complement(clause)
                    if self.classifier.facet_relation_events
                    else self._is_complement_removal(clause)
                )
            ):
                # `분말 외의 다른 제형` names the selected value only to
                # describe its complement.  It must not overwrite 분말=MUST
                # with an EXCLUDE event.
                has_committed_anchor = any(
                    any(
                        (event.facet_name, event.value_code) == key
                        and event.target_role not in {"COMPLEMENT", "COMPLEMENT_OF"}
                        and event.modality == "COMMITTED"
                        and event.polarity is not None
                        for event in events
                    )
                    for key in explicit_targets
                )
                if self.classifier.facet_set_algebra and not has_committed_anchor:
                    derived_anchor_polarity = self._complement_anchor_polarity(clause)
                    target_role = "DERIVED_ANCHOR"
                elif has_committed_anchor:
                    target_role = (
                        "COMPLEMENT_OF"
                        if self.classifier.facet_relation_events
                        else "COMPLEMENT"
                    )
            if not targets and last_targets:
                non_constraint_inquiry = bool(
                    self.classifier.facet_set_algebra
                    and NON_CONSTRAINT_INQUIRY_PATTERN.search(normalize(clause))
                )
                complement_removal = (
                    self.classifier.predicate_argument_temporal_scope
                    and (
                        self._is_facet_relation_complement(clause)
                        if self.classifier.facet_relation_events
                        else self._is_complement_removal(clause)
                    )
                )
                typed_reference = bool(
                    self.classifier.typed_reference_event_roles
                    and TYPED_COREFERENCE_PATTERN.search(normalize(clause))
                    and not non_constraint_inquiry
                )
                current_relation_override = bool(
                    self.classifier.facet_relation_events
                    and has_predicate_signal
                    and TYPED_CURRENT_OVERRIDE_PATTERN.search(normalize(clause))
                )
                explicit_relation_action = bool(
                    self.classifier.facet_relation_events
                    and has_predicate_signal
                    and polarity is not None
                )
                temporal_relation_continuation = bool(
                    self.classifier.facet_relation_events
                    and has_predicate_signal
                    and FACET_RELATION_TARGETLESS_TEMPORAL_PATTERN.search(
                        normalize(clause)
                    )
                )
                if complement_removal and self.classifier.typed_reference_event_roles:
                    targets = last_targets
                    has_committed_anchor = any(
                        any(
                            (event.facet_name, event.value_code) == key
                            and event.target_role not in {"COMPLEMENT", "COMPLEMENT_OF"}
                            and event.modality == "COMMITTED"
                            and event.polarity is not None
                            for event in events
                        )
                        for key in last_targets
                    )
                    if self.classifier.facet_set_algebra and not has_committed_anchor:
                        target_role = "DERIVED_ANCHOR"
                        derived_anchor_polarity = self._complement_anchor_polarity(clause)
                    else:
                        target_role = (
                            "COMPLEMENT_OF"
                            if self.classifier.facet_relation_events
                            else "COMPLEMENT"
                        )
                elif not complement_removal and (
                    (
                        has_predicate_signal
                        and not self.classifier.facet_relation_events
                    )
                    or current_relation_override
                    or explicit_relation_action
                    or temporal_relation_continuation
                    or (
                        PREDICATE_COREFERENCE_PATTERN.search(normalize(clause))
                        and not non_constraint_inquiry
                    )
                    or typed_reference
                ):
                    targets = last_targets
                    target_role = "COREFERENCE"
            if not targets:
                continue

            for key in dict.fromkeys(targets):
                facet = facets_by_key.get(key)
                if facet is None:
                    # Explicit facets are registered before last_targets changes;
                    # this branch is defensive for malformed matcher output.
                    continue
                relation_type = self._relation_override(
                    category_id,
                    clause,
                    facet.facet_name,
                    facet.value_code,
                )
                event_polarity = derived_anchor_polarity or relation_type or polarity
                event_modality = modality
                previous = next(
                    (
                        item
                        for item in reversed(events)
                        if (item.facet_name, item.value_code) == key
                        and item.target_role not in {"COMPLEMENT", "COMPLEMENT_OF"}
                        and item.modality == "COMMITTED"
                        and item.polarity is not None
                    ),
                    None,
                )
                if (
                    self.classifier.typed_reference_event_roles
                    and target_role == "COREFERENCE"
                ):
                    framed_signals = self._framed_predicate_signals(clause)
                    has_explicit_polarity = any(
                        signal.polarity is not None
                        and signal.source != "FRAME_GENERIC_SELECTION"
                        for signal in framed_signals
                    )
                    if (
                        not has_explicit_polarity
                        and REFERENCE_CONFIRM_PATTERN.search(normalize(clause))
                        and previous is not None
                    ):
                        event_modality = "COMMITTED"
                        event_polarity = previous.polarity
                if (
                    event_polarity is None
                    and event_modality == "COMMITTED"
                    and self.classifier.morphological_predicate_events
                    and not explicit_targets
                ):
                    if previous is not None:
                        event_polarity = previous.polarity
                if event_polarity is None and event_modality == "COMMITTED":
                    event_modality = "TENTATIVE"
                events.append(FacetEvent(
                    facet_name=facet.facet_name,
                    value_code=facet.value_code,
                    value=facet.value,
                    polarity=event_polarity,
                    modality=event_modality,
                    order=order,
                    evidence_clause=clause,
                    target_role=target_role,
                    anchor_facet_name=(
                        facet.facet_name if target_role == "COMPLEMENT_OF" else None
                    ),
                    anchor_value_code=(
                        facet.value_code if target_role == "COMPLEMENT_OF" else None
                    ),
                ))

            if explicit_targets and target_role not in {"COMPLEMENT", "COMPLEMENT_OF"}:
                last_targets = explicit_targets

        if not facets_by_key:
            status = "NONE" if any(pattern in normalized for pattern in NO_REQUIREMENT_PATTERNS) else "REVIEW"
            warning = () if status == "NONE" else ("NO_FACET_CONSTRAINT_EXTRACTED",)
            return ExtractionResult(status, (), warning, clauses)

        latest: dict[tuple[str, int], FacetEvent] = {}
        for event in events:
            if event.target_role in {"COMPLEMENT", "COMPLEMENT_OF"}:
                continue
            latest[(event.facet_name, event.value_code)] = event
        unresolved = [
            event
            for event in latest.values()
            if event.modality != "COMMITTED" or event.polarity is None
        ]
        missing = set(facets_by_key) - set(latest)
        if unresolved or missing:
            warnings = [
                f"PREDICATE_EVENT_UNRESOLVED:{event.value}:{event.modality}:{event.polarity or 'NONE'}"
                for event in unresolved
            ]
            warnings.extend(
                f"PREDICATE_EVENT_MISSING:{facets_by_key[key].value}" for key in sorted(missing)
            )
            return ExtractionResult("REVIEW", (), tuple(warnings), clauses)

        constraints = tuple(
            FacetConstraint(
                facet_name=event.facet_name,
                value_code=event.value_code,
                value=event.value,
                constraint_type=event.polarity or "MUST",
                evidence_clause=event.evidence_clause,
            )
            for _, event in sorted(latest.items(), key=lambda item: item[1].order)
        )
        return ExtractionResult("PARSED", constraints, (), clauses)

    def _extract_with_event_state_machine(
        self,
        category_id: str,
        text: str,
    ) -> ExtractionResult:
        """Resolve final constraints by ordered events for each mentioned facet."""
        normalized = normalize(text)
        if any(pattern in normalized for pattern in ALTERNATIVE_PATTERNS):
            return ExtractionResult("REVIEW", (), ("ALTERNATIVE_VALUE_SCOPE",), (text,))
        if "아니면" in normalized and not self.classifier.is_positive_double_negative(normalized):
            return ExtractionResult("REVIEW", (), ("ALTERNATIVE_VALUE_SCOPE",), (text,))

        base_clauses = self.split_clauses(category_id, text)
        explicitly_split = tuple(
            expanded
            for clause in base_clauses
            for expanded in self._split_explicit_multi_value_clause(category_id, clause)
        )
        clauses = tuple(
            scoped
            for clause in explicitly_split
            for scoped in self._split_candidate_pool_scope(category_id, clause)
        )
        events: list[FacetEvent] = []
        facets_by_key = {}
        last_targets: tuple[tuple[str, int], ...] = ()

        for order, clause in enumerate(clauses):
            facet_result = self.matcher.match(category_id, clause)
            if facet_result.warnings:
                return ExtractionResult(
                    "REVIEW",
                    (),
                    tuple(f"{warning}: {clause}" for warning in facet_result.warnings),
                    clauses,
                )
            explicit_targets = tuple(
                (facet.facet_name, facet.value_code) for facet in facet_result.facets
            )
            for facet in facet_result.facets:
                facets_by_key[(facet.facet_name, facet.value_code)] = facet
            if explicit_targets:
                last_targets = explicit_targets

            classification = self.classifier.classify(
                clause,
                tuple(facet.value for facet in facet_result.facets),
            )
            modality = self._event_modality(clause, classification.constraint_type)
            polarity = self._event_polarity(clause, classification.constraint_type)

            targets = explicit_targets
            if not targets and last_targets:
                value = normalize(clause)
                carries_previous_target = (
                    EVENT_COREFERENCE_PATTERN.search(value)
                    or any(pattern.search(value) for pattern in EVENT_CANCEL_PATTERNS)
                    or EVENT_REMOVE_PATTERN.search(value)
                    or EVENT_PREFER_PATTERN.search(value)
                )
                if carries_previous_target:
                    targets = last_targets
            if not targets:
                continue

            if any(pattern in normalize(clause) for pattern in NO_REQUIREMENT_PATTERNS):
                # Retain the explicit target for a following coreferential ranking
                # clause, but do not turn indifference itself into a constraint.
                continue

            for key in dict.fromkeys(targets):
                facet = facets_by_key[key]
                relation_type = self._relation_override(
                    category_id,
                    clause,
                    facet.facet_name,
                    facet.value_code,
                )
                event_polarity = relation_type or polarity
                event_modality = modality
                if event_polarity is None and event_modality == "COMMITTED":
                    event_modality = "TENTATIVE"
                events.append(FacetEvent(
                    facet_name=facet.facet_name,
                    value_code=facet.value_code,
                    value=facet.value,
                    polarity=event_polarity,
                    modality=event_modality,
                    order=order,
                    evidence_clause=clause,
                ))

        if not facets_by_key:
            status = "NONE" if any(pattern in normalized for pattern in NO_REQUIREMENT_PATTERNS) else "REVIEW"
            warning = () if status == "NONE" else ("NO_FACET_CONSTRAINT_EXTRACTED",)
            return ExtractionResult(status, (), warning, clauses)

        latest: dict[tuple[str, int], FacetEvent] = {}
        for event in events:
            latest[(event.facet_name, event.value_code)] = event
        unresolved = [
            event
            for event in latest.values()
            if event.modality != "COMMITTED" or event.polarity is None
        ]
        missing = set(facets_by_key) - set(latest)
        if unresolved or missing:
            warnings = [
                f"EVENT_UNRESOLVED:{event.value}:{event.modality}:{event.polarity or 'NONE'}"
                for event in unresolved
            ]
            warnings.extend(
                f"EVENT_MISSING:{facets_by_key[key].value}" for key in sorted(missing)
            )
            return ExtractionResult("REVIEW", (), tuple(warnings), clauses)

        constraints = tuple(
            FacetConstraint(
                facet_name=event.facet_name,
                value_code=event.value_code,
                value=event.value,
                constraint_type=event.polarity or "MUST",
                evidence_clause=event.evidence_clause,
            )
            for _, event in sorted(latest.items(), key=lambda item: item[1].order)
        )
        return ExtractionResult("PARSED", constraints, (), clauses)

    def split_clauses(self, category_id: str, text: str) -> tuple[str, ...]:
        """Split at strong punctuation and selected connective endings, not conditional -면."""
        boundaries = {0, len(text)}
        protected_spans = self.matcher.protected_spans(category_id, text)
        tokens = self.kiwi.tokenize(text)
        for index, token in enumerate(tokens):
            token_end = token.start + token.len
            punctuation_tags = {"SP", "SF", "SE"} if self.classifier.split_soft_punctuation else {"SF", "SE"}
            if token.tag in punctuation_tags:
                if any(start < token.start < end for start, end in protected_spans):
                    continue
                boundaries.add(token.start)
                boundaries.add(token_end)
            elif (
                token.form in CONNECTIVE_ENDINGS
                and token.tag in {"EC", "XPN"}
                # `찾고 있습니다` is one progressive selection action, not two
                # independent clauses.  Kiwi marks the following auxiliary as VX.
                and not (index + 1 < len(tokens) and tokens[index + 1].tag == "VX")
                # Chained selection actions share one facet scope:
                # `결정하고 주문합니다`, `찾고 있는데 보여 주세요`.
                and not (
                    any(item.form in SELECTION_ACTION_FORMS for item in tokens[:index])
                    and any(item.form in SELECTION_ACTION_FORMS for item in tokens[index + 1:])
                )
            ):
                boundaries.add(token_end)
            elif token.form in CONJUNCTIONS:
                boundaries.add(token.start)
        points = sorted(boundaries)
        clauses = []
        for start, end in zip(points, points[1:]):
            clause = text[start:end].strip(" ,.;!?\t\n")
            if clause and clause not in CONJUNCTIONS:
                clauses.append(clause)
        return tuple(clauses)

    def _split_explicit_multi_value_clause(self, category_id: str, clause: str) -> tuple[str, ...]:
        """Split compressed same-facet clauses only when every value has an explicit marker.

        This accepts `분말은 꼭 필요 액상은 제외` while leaving shared-marker,
        comparative, and alternative expressions on the REVIEW path.
        """
        occurrences = self.matcher.occurrences(category_id, clause)
        by_facet = {}
        for occurrence in occurrences:
            by_facet.setdefault(occurrence.facet.facet_name, []).append(occurrence)
        repeated = [
            items for items in by_facet.values()
            if len({item.facet.value_code for item in items}) > 1
        ]
        if len(repeated) != 1:
            return (clause,)

        first_by_code = {}
        for occurrence in repeated[0]:
            first_by_code.setdefault(occurrence.facet.value_code, occurrence)
        ordered = sorted(first_by_code.values(), key=lambda item: item.start)
        starts = [item.start for item in ordered]
        parts = [
            clause[start:end].strip(" ,.;!?\t\n")
            for start, end in zip([0, *starts[1:]], [*starts[1:], len(clause)])
        ]
        if not all(parts):
            return (clause,)

        # Do not infer multiple default MUSTs. Each compressed segment must carry
        # its own explicit modality marker.
        for part in parts:
            matches = self.matcher.match(category_id, part)
            if matches.warnings or len(matches.facets) != 1:
                return (clause,)
            classification = self.classifier.classify(
                part,
                tuple(item.value for item in matches.facets),
            )
            if classification.constraint_type == "REVIEW" or not classification.matched_markers:
                return (clause,)
        return tuple(parts)

    def _split_candidate_pool_scope(self, category_id: str, clause: str) -> tuple[str, ...]:
        """Separate a candidate-pool condition from a following ranked facet.

        Example: `하루 두 번 먹는 제품 중 프로바이오틱스를 우선` means the
        frequency constrains the pool, while `우선` modifies only the ingredient.
        """
        occurrences = self.matcher.occurrences(category_id, clause)
        distinct = []
        seen = set()
        for occurrence in occurrences:
            key = (occurrence.facet.facet_name, occurrence.facet.value_code, occurrence.start)
            if key not in seen:
                seen.add(key)
                distinct.append(occurrence)
        for previous, following in zip(distinct, distinct[1:]):
            between = normalize(clause[previous.end:following.start])
            if previous.facet.facet_name != following.facet.facet_name and "중" in between:
                left = clause[:following.start].strip(" ,.;!?\t\n")
                right = clause[following.start:].strip(" ,.;!?\t\n")
                if left and right:
                    return (left, right)
        return (clause,)

    def _split_facet_predicate_ledger_clause(
        self,
        category_id: str,
        clause: str,
    ) -> tuple[str, ...]:
        """Bind each distinct taxonomy occurrence to its following predicate span.

        Earlier versions classified a whole clause once, so the final predicate
        leaked to every facet in expressions such as
        `환은 우선, 1일 2회는 제외`.  This split is deliberately
        conservative: it only separates non-overlapping, distinct facet keys.
        """
        occurrences = sorted(
            self.matcher.occurrences(category_id, clause),
            key=lambda item: (item.start, -(item.end - item.start)),
        )
        distinct = []
        seen_keys = set()
        covered_until = -1
        for occurrence in occurrences:
            key = (occurrence.facet.facet_name, occurrence.facet.value_code)
            if occurrence.start < covered_until or key in seen_keys:
                continue
            seen_keys.add(key)
            covered_until = occurrence.end
            distinct.append(occurrence)
        if len(distinct) < 2:
            return (clause,)

        parts = []
        starts = [item.start for item in distinct]
        for index, (start, end) in enumerate(
            zip([0, *starts[1:]], [*starts[1:], len(clause)])
        ):
            part = clause[start:end].strip(" ,.;!?\t\n")
            if not part:
                return (clause,)
            matches = self.matcher.match(category_id, part)
            if matches.warnings or not matches.facets:
                return (clause,)
            parts.append(part)
        return tuple(parts)

    def _has_cross_facet_temporal_override(
        self,
        category_id: str,
        text: str,
        deferred_start: int,
        deferred_end: int,
    ) -> bool:
        """Detect a deferred facet followed by a current decision on another facet."""
        occurrences = self.matcher.occurrences(category_id, text)
        deferred_keys = {
            (item.facet.facet_name, item.facet.value_code)
            for item in occurrences
            if item.start < deferred_start
        }
        tail_keys = {
            (item.facet.facet_name, item.facet.value_code)
            for item in occurrences
            if item.start >= deferred_end
        }
        return bool(deferred_keys and tail_keys - deferred_keys)

    def _is_facet_relation_complement(self, clause: str) -> bool:
        """Return whether an action targets the set complementary to an anchor.

        The named value in `바 외에는 제거` is an anchor.  It is not
        the object of REMOVE.  Positive selection of `다른 제형만` is
        also a complement action and must not overwrite the anchor's state.
        """
        value = normalize(clause)
        reference = FACET_RELATION_COMPLEMENT_REFERENCE_PATTERN.search(value)
        if not reference:
            return False
        return bool(
            TYPED_COMPLEMENT_ACTION_PATTERN.search(value)
            or FACET_RELATION_COMPLEMENT_SELECTION_PATTERN.search(value)
            or FACET_RELATION_COMPLEMENT_POSITIVE_TAIL_PATTERN.search(
                value[reference.start():]
            )
        )

    @staticmethod
    def _complement_anchor_polarity(clause: str) -> str | None:
        """Reduce an exhaustive complement operation to its anchor constraint."""
        value = normalize(clause)
        reference = FACET_RELATION_COMPLEMENT_REFERENCE_PATTERN.search(value)
        if not reference:
            return None
        tail = value[reference.start():]
        if TYPED_COMPLEMENT_ACTION_PATTERN.search(tail):
            return "MUST"
        if FACET_RELATION_COMPLEMENT_SELECTION_PATTERN.search(tail):
            return "EXCLUDE"
        if FACET_RELATION_COMPLEMENT_POSITIVE_TAIL_PATTERN.search(tail):
            return "EXCLUDE"
        return None

    def _speaker_scope(self, text: str) -> SpeakerScope:
        """Represent whether a constraint belongs to the user or a quotation."""
        normalized = normalize(text)
        third_party = SPEAKER_THIRD_PARTY_PATTERN.search(normalized)
        reported_action = SPEAKER_REPORTED_ACTION_PATTERN.search(normalized)
        if not third_party or not reported_action:
            return SpeakerScope("USER", "ACCEPTED", (0, len(text)))

        evidence_start = min(third_party.start(), reported_action.start())
        evidence_end = max(third_party.end(), reported_action.end())
        if SPEAKER_REJECTION_PATTERN.search(normalized[evidence_start:]):
            return SpeakerScope(
                "REPORTED", "REJECTED", (evidence_start, len(text))
            )
        if SPEAKER_ACCEPTANCE_PATTERN.search(normalized[evidence_start:]):
            return SpeakerScope(
                "USER", "ACCEPTED", (evidence_start, len(text))
            )
        return SpeakerScope(
            "REPORTED", "UNRESOLVED", (evidence_start, evidence_end)
        )

    def _request_provenance_scope(
        self,
        category_id: str,
        text: str,
    ) -> SpeakerScope:
        """Apply a request-level provenance firewall to third-party language.

        A third-party cue taints the whole request.  Recovery is deliberately
        all-or-nothing: a later user acceptance must be followed by a repeated
        taxonomy key and an independently parseable final constraint for every
        taxonomy key mentioned in the reported portion.
        """
        if self.classifier.kiwi_quotation_segment_boundary:
            return self._kiwi_quotation_minimal_tail_scope(category_id, text)
        if self.classifier.reported_segment_user_tail:
            return self._reported_segment_user_tail_scope(category_id, text)

        normalized = normalize(text)
        third_party = SPEAKER_THIRD_PARTY_PATTERN.search(normalized)
        if third_party is None:
            return SpeakerScope("USER", "ACCEPTED", (0, len(text)))

        acceptances = tuple(
            SPEAKER_ACCEPTANCE_PATTERN.finditer(normalized, third_party.end())
        )
        rejections = tuple(
            SPEAKER_REJECTION_PATTERN.finditer(normalized, third_party.end())
        )
        latest_acceptance = acceptances[-1] if acceptances else None
        latest_rejection = rejections[-1] if rejections else None
        if latest_rejection is not None and (
            latest_acceptance is None
            or latest_rejection.end() >= latest_acceptance.end()
        ):
            return SpeakerScope(
                "REPORTED", "REJECTED", (third_party.start(), len(text))
            )
        if latest_acceptance is None:
            return SpeakerScope(
                "REPORTED", "UNRESOLVED", (third_party.start(), len(text))
            )

        source_occurrences = tuple(
            item
            for item in self.matcher.occurrences(category_id, text)
            if item.start < latest_acceptance.start()
        )
        tail_occurrences = tuple(
            item
            for item in self.matcher.occurrences(category_id, text)
            if item.start >= latest_acceptance.end()
        )
        source_keys = {
            (item.facet.facet_name, item.facet.value_code)
            for item in source_occurrences
        }
        tail_keys = {
            (item.facet.facet_name, item.facet.value_code)
            for item in tail_occurrences
        }
        if not source_keys or not source_keys.issubset(tail_keys):
            return SpeakerScope(
                "REPORTED", "UNRESOLVED", (third_party.start(), len(text))
            )

        tail = text[latest_acceptance.end():]
        tail_result = self._extract_with_unified_predicate_frame_ledger(
            category_id, tail
        )
        proven_tail_keys = {
            (item.facet_name, item.value_code)
            for item in tail_result.constraints
        }
        if (
            tail_result.status != "PARSED"
            or not source_keys.issubset(proven_tail_keys)
        ):
            return SpeakerScope(
                "REPORTED", "UNRESOLVED", (third_party.start(), len(text))
            )
        return SpeakerScope(
            "USER", "ACCEPTED", (latest_acceptance.start(), len(text))
        )

    @staticmethod
    def _strong_user_tail_is_final(text: str) -> bool:
        """Require a strong request after every weak/tentative tail marker."""
        strong = tuple(STRONG_USER_FINAL_ACTION_PATTERN.finditer(normalize(text)))
        if not strong:
            return False
        if REPORTED_TAIL_EMBEDDING_PATTERN.search(normalize(text)):
            return False
        weak = tuple(WEAK_USER_TAIL_MODALITY_PATTERN.finditer(normalize(text)))
        if not weak:
            return True
        return strong[-1].start() > weak[-1].end()

    def _reported_segment_user_tail_scope(
        self,
        category_id: str,
        text: str,
    ) -> SpeakerScope:
        """Separate reported discourse from an independently committed tail.

        Ownership recovery no longer depends on enumerating acceptance words.
        Every taxonomy key seen before the candidate tail must be repeated and
        independently constrained by a strong sentence-level action in the tail.
        """
        normalized = normalize(text)
        third_party = SPEAKER_THIRD_PARTY_PATTERN.search(normalized)
        report_event = REPORTED_COMPLEMENT_EVENT_PATTERN.search(normalized)
        if third_party is None and report_event is None:
            return SpeakerScope("USER", "ACCEPTED", (0, len(text)))

        risk_start = min(
            match.start()
            for match in (third_party, report_event)
            if match is not None
        )
        occurrences = tuple(self.matcher.occurrences(category_id, text))
        if not occurrences:
            return SpeakerScope(
                "REPORTED",
                "UNRESOLVED",
                (risk_start, len(text)),
                reported_span=(risk_start, len(text)),
            )

        by_key: dict[tuple[str, int], list] = {}
        for occurrence in occurrences:
            key = (occurrence.facet.facet_name, occurrence.facet.value_code)
            by_key.setdefault(key, []).append(occurrence)
        last_occurrences = [items[-1] for items in by_key.values()]
        tail_start = min(item.start for item in last_occurrences)
        source_keys = {
            (item.facet.facet_name, item.facet.value_code)
            for item in occurrences
            if item.start < tail_start
        }
        tail_keys = {
            (item.facet.facet_name, item.facet.value_code)
            for item in occurrences
            if item.start >= tail_start
        }
        if not source_keys or not source_keys.issubset(tail_keys):
            return SpeakerScope(
                "REPORTED",
                "UNRESOLVED",
                (risk_start, len(text)),
                reported_span=(risk_start, len(text)),
            )

        tail = text[tail_start:]
        if not self._strong_user_tail_is_final(tail):
            return SpeakerScope(
                "REPORTED",
                "UNRESOLVED",
                (risk_start, len(text)),
                reported_span=(risk_start, tail_start),
                user_tail_span=(tail_start, len(text)),
                tail_proof_source="WEAK_OR_MISSING_FINAL_ACTION",
            )
        tail_result = self._extract_with_unified_predicate_frame_ledger(
            category_id, tail
        )
        proven_tail_keys = {
            (item.facet_name, item.value_code)
            for item in tail_result.constraints
        }
        if (
            tail_result.status != "PARSED"
            or not source_keys.issubset(proven_tail_keys)
        ):
            return SpeakerScope(
                "REPORTED",
                "UNRESOLVED",
                (risk_start, len(text)),
                reported_span=(risk_start, tail_start),
                user_tail_span=(tail_start, len(text)),
                tail_proof_source="TAIL_CONSTRAINT_NOT_PROVEN",
            )
        return SpeakerScope(
            "USER",
            "ACCEPTED",
            (risk_start, len(text)),
            reported_span=(risk_start, tail_start),
            user_tail_span=(tail_start, len(text)),
            tail_proof_source="REPEATED_TAXONOMY_STRONG_FINAL_ACTION",
        )

    def _kiwi_quotation_boundaries(self, text: str) -> tuple[int, ...]:
        """Return grammar-level quotation boundaries without report-verb lexicons."""
        boundaries = []
        for token in self.matcher.kiwi.tokenize(text):
            if self.classifier.kiwi_reported_ending_role_v2 and self._is_reported_ending_token(
                token.tag, token.form
            ):
                boundaries.append(token.start + token.len)
            elif (
                self.classifier.typed_korean_ending_roles
                and token.tag == "EC"
                and (
                    token.form == "라"
                    or token.form.endswith(("라고", "으라고", "다고", "자고", "냐고"))
                )
            ):
                boundaries.append(token.start + token.len)
            elif (
                self.classifier.typed_korean_ending_roles
                and token.tag == "ETM"
                and token.form.endswith(("라는", "다는", "자는", "냐는"))
            ):
                boundaries.append(token.start + token.len)
            elif token.tag == "EC" and re.fullmatch(
                r"(?:으)?(?:라|다|자|냐)고", token.form
            ):
                boundaries.append(token.start + token.len)
            elif token.tag == "JKQ" and token.form.endswith("고"):
                boundaries.append(token.start + token.len)
        return tuple(sorted(set(boundaries)))

    @staticmethod
    def _is_reported_ending_token(tag: str, form: str) -> bool:
        """Map Kiwi quote/connective forms to one REPORTED_BOUNDARY role."""
        if tag == "JKQ":
            return form.endswith("고")
        if tag == "ETM":
            return form.endswith(("라는", "다는", "자는", "냐는", "느냐는"))
        if tag != "EC":
            return False
        quote_stems = (
            "라", "으라", "다", "ᆫ다", "ㄴ다", "는다", "자", "냐", "느냐",
        )
        linkers = ("", "고", "며", "면서", "길래")
        return any(form == stem + linker for stem in quote_stems for linker in linkers)

    @staticmethod
    def _explicit_user_tail_boundaries(text: str) -> tuple[int, ...]:
        markers = re.compile(
            r"(?:저는|저도|제가|나는|나도|내가|난|전|이번\s*구매)"
        )
        return tuple(match.start() for match in markers.finditer(text))

    def _taxonomy_echo_only(
        self,
        category_id: str,
        text: str,
        required_keys: set[tuple[str, int]],
    ) -> bool:
        """Accept only a trailing repetition of already-bound taxonomy values."""
        if not text.strip():
            return True
        occurrences = tuple(self.matcher.occurrences(category_id, text))
        if not occurrences:
            return False
        if {
            (item.facet.facet_name, item.facet.value_code)
            for item in occurrences
        } - required_keys:
            return False
        ignorable_tags = {
            "JX", "JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ",
            "JC", "SF", "SP", "SS", "SSO", "SSC", "SE", "SW",
        }
        for token in self.matcher.kiwi.tokenize(text):
            token_start = token.start
            token_end = token.start + token.len
            if any(
                token_start >= item.start and token_end <= item.end
                for item in occurrences
            ):
                continue
            if token.tag in ignorable_tags:
                continue
            return False
        return True

    def _minimal_proven_span_end(
        self,
        category_id: str,
        tail: str,
        required_keys: set[tuple[str, int]],
    ) -> int | None:
        """End at the first proof whose remainder is only a taxonomy echo."""
        ends = {len(tail)}
        for token in self.matcher.kiwi.tokenize(tail):
            end = token.start + token.len
            if self._taxonomy_echo_only(category_id, tail[end:], required_keys):
                ends.add(end)
        for end in sorted(ends):
            candidate = tail[:end]
            candidate_keys = {
                (item.facet.facet_name, item.facet.value_code)
                for item in self.matcher.occurrences(category_id, candidate)
            }
            if not required_keys.issubset(candidate_keys):
                continue
            if self._proof_ordered_user_tail(
                category_id, candidate, required_keys
            ):
                return end
        return None

    def _proof_ordered_user_tail(
        self,
        category_id: str,
        tail: str,
        required_keys: set[tuple[str, int]],
    ) -> bool:
        """Validate a tail with constraint proof order, not ending vocabulary."""
        baseline = self._extract_with_unified_predicate_frame_ledger(
            category_id, tail
        )
        if baseline.status != "PARSED":
            return False
        proofed = self._extract_with_proof_carrying_constraint_gate(
            category_id, tail, baseline
        )
        if proofed.status != "PARSED":
            return False
        proven_keys = {
            (item.facet_name, item.value_code)
            for item in proofed.constraints
        }
        if not required_keys.issubset(proven_keys):
            return False
        final_orders = [
            item.proof.final_state_order
            for item in proofed.constraints
            if item.proof is not None
            and (item.facet_name, item.value_code) in required_keys
        ]
        if len(final_orders) != len(required_keys):
            return False
        weak_pattern = (
            TYPED_TAIL_UNRESOLVED_MODALITY_PATTERN
            if self.classifier.typed_user_tail_modality
            else WEAK_USER_TAIL_MODALITY_PATTERN
        )
        weak = tuple(weak_pattern.finditer(normalize(tail)))
        if weak and max(match.end() for match in weak) >= min(final_orders):
            return False
        return True

    def _kiwi_quotation_minimal_tail_scope(
        self,
        category_id: str,
        text: str,
    ) -> SpeakerScope:
        """Find the earliest complete, proven user suffix after reported speech."""
        normalized = normalize(text)
        third_party = SPEAKER_THIRD_PARTY_PATTERN.search(normalized)
        quotation_boundaries = self._kiwi_quotation_boundaries(text)
        owner_boundaries = (
            self._explicit_user_tail_boundaries(text)
            if self.classifier.explicit_user_tail_owner_boundary
            else ()
        )
        if (
            self.classifier.occurrence_predicate_proof
            and third_party is None
            and not quotation_boundaries
        ):
            return SpeakerScope("USER", "ACCEPTED", (0, len(text)))
        if third_party is None and not quotation_boundaries and not owner_boundaries:
            return SpeakerScope("USER", "ACCEPTED", (0, len(text)))

        occurrences = tuple(self.matcher.occurrences(category_id, text))
        risk_start = (
            min(
                [
                    *(match.start() for match in (third_party,) if match is not None),
                    *(max(0, boundary - 3) for boundary in quotation_boundaries),
                    *(0 for _ in owner_boundaries),
                ]
            )
            if third_party is not None or quotation_boundaries or owner_boundaries
            else 0
        )
        if not occurrences:
            return SpeakerScope(
                "REPORTED",
                "UNRESOLVED",
                (risk_start, len(text)),
                reported_span=(risk_start, len(text)),
            )

        boundaries = [*quotation_boundaries, *owner_boundaries]
        if third_party is not None and not boundaries:
            first_taxonomy_end = min(item.end for item in occurrences)
            boundaries.extend(
                match.end()
                for match in re.finditer(r"[,.;!?]", text)
                if match.end() > first_taxonomy_end
            )
        for boundary in sorted(set(boundaries)):
            source_keys = {
                (item.facet.facet_name, item.facet.value_code)
                for item in occurrences
                if item.end <= boundary
            }
            tail_occurrences = tuple(
                item for item in occurrences if item.start >= boundary
            )
            if not source_keys or not tail_occurrences:
                continue
            tail_start = tail_occurrences[0].start
            tail_keys = {
                (item.facet.facet_name, item.facet.value_code)
                for item in tail_occurrences
            }
            if not source_keys.issubset(tail_keys):
                continue
            tail = text[tail_start:]
            tail_end = len(tail)
            if self.classifier.minimal_proven_user_span:
                proven_end = self._minimal_proven_span_end(
                    category_id, tail, source_keys
                )
                if proven_end is None:
                    continue
                tail_end = proven_end
            elif not self._proof_ordered_user_tail(category_id, tail, source_keys):
                continue
            return SpeakerScope(
                "USER",
                "ACCEPTED",
                (risk_start, len(text)),
                reported_span=(risk_start, tail_start),
                user_tail_span=(tail_start, tail_start + tail_end),
                tail_proof_source=(
                    "KIWI_QUOTATION_MINIMAL_PROVEN_SPAN"
                    if self.classifier.minimal_proven_user_span
                    else "KIWI_QUOTATION_MINIMAL_PROVEN_SUFFIX"
                ),
            )

        return SpeakerScope(
            "REPORTED",
            "UNRESOLVED",
            (risk_start, len(text)),
            reported_span=(risk_start, len(text)),
            tail_proof_source="NO_COMPLETE_PROOF_ORDERED_SUFFIX",
        )

    @staticmethod
    def _offset_tail_result(
        result: ExtractionResult,
        offset: int,
        speaker_scope: SpeakerScope,
        original_text: str,
    ) -> ExtractionResult:
        """Promote proof spans from an isolated user tail to document offsets."""
        promoted: list[FacetConstraint] = []
        for constraint in result.constraints:
            proof = constraint.proof
            if proof is not None:
                filter_operation = proof.filter_operation
                if filter_operation is not None:
                    filter_operation = replace(
                        filter_operation,
                        criterion_span=(
                            filter_operation.criterion_span[0] + offset,
                            filter_operation.criterion_span[1] + offset,
                        ),
                        predicate_span=(
                            filter_operation.predicate_span[0] + offset,
                            filter_operation.predicate_span[1] + offset,
                        ),
                    )
                proof = replace(
                    proof,
                    taxonomy_span=(
                        proof.taxonomy_span[0] + offset,
                        proof.taxonomy_span[1] + offset,
                    ),
                    predicate_span=(
                        proof.predicate_span[0] + offset,
                        proof.predicate_span[1] + offset,
                    ),
                    final_state_order=proof.final_state_order + offset,
                    filter_operation=filter_operation,
                    speaker_scope=speaker_scope,
                )
            promoted.append(replace(constraint, proof=proof))
        return ExtractionResult(
            result.status,
            tuple(promoted),
            result.warnings,
            (original_text,),
        )

    def _explicit_filter_result_operation(
        self,
        category_id: str,
        text: str,
        facet_name: str,
        value_code: int,
    ) -> FilterOperation | None:
        """Accept only an explicit, final KEEP/REMOVE result around a filter.

        This guard does not infer that `X로 필터` means KEEP.  It requires a
        visible result such as `X만 남김/유지/표시` or `X를 걸러내서 제외`.
        When the value is repeated, the latest explicit result wins.
        """
        filter_matches = tuple(PROOF_FILTER_ACTION_PATTERN.finditer(text))
        if not filter_matches:
            return None
        occurrences = tuple(
            item
            for item in self.matcher.occurrences(category_id, text)
            if (item.facet.facet_name, item.facet.value_code)
            == (facet_name, value_code)
        )
        if not occurrences:
            return None

        events: list[tuple[int, int, str, str, str]] = []
        for occurrence in occurrences:
            tail_end = min(len(text), occurrence.end + 120)
            tail = text[occurrence.end:tail_end]
            complement = EXPLICIT_FILTER_COMPLEMENT_PATTERN.match(tail)

            keep = EXPLICIT_FILTER_KEEP_AFTER_VALUE_PATTERN.match(tail)
            if keep is not None:
                events.append((
                    occurrence.end + keep.start(),
                    occurrence.end + keep.end(),
                    "KEEP",
                    "SELECTED_VALUE",
                    "EXPLICIT_FINAL_KEEP",
                ))

            # A co-referential result can be farther from the named criterion,
            # but it is valid only after the filter head owned by this key.
            key_filter = next(
                (
                    match
                    for match in filter_matches
                    if occurrence.start - 28 <= match.start() <= tail_end
                ),
                None,
            )
            if key_filter is not None:
                coreferential_tail = text[key_filter.end():tail_end]
                coreferential = EXPLICIT_FILTER_COREFERENTIAL_KEEP_PATTERN.search(
                    coreferential_tail
                )
                if coreferential is not None:
                    events.append((
                        key_filter.end() + coreferential.start(),
                        key_filter.end() + coreferential.end(),
                        "KEEP",
                        "COREFERENTIAL_RESULT",
                        "EXPLICIT_COREFERENTIAL_KEEP",
                    ))

            if complement is None:
                removal = EXPLICIT_FILTER_REMOVE_AFTER_VALUE_PATTERN.match(tail)
                if removal is not None:
                    events.append((
                        occurrence.end + removal.start(),
                        occurrence.end + removal.end(),
                        "REMOVE",
                        "NAMED_OBJECT",
                        "EXPLICIT_FINAL_REMOVE",
                    ))
                direct_removal = EXPLICIT_FILTER_DIRECT_REMOVE_PATTERN.match(tail)
                if direct_removal is not None:
                    events.append((
                        occurrence.end + direct_removal.start(),
                        occurrence.end + direct_removal.end(),
                        "REMOVE",
                        "NAMED_OBJECT",
                        "EXPLICIT_FILTER_OUT",
                    ))

        criterion_span = (
            min(item.start for item in occurrences),
            max(item.end for item in occurrences),
        )
        if not events:
            nearest_filter = min(
                filter_matches,
                key=lambda match: min(
                    abs(match.start() - item.end) for item in occurrences
                ),
            )
            if min(
                abs(nearest_filter.start() - item.end) for item in occurrences
            ) > 96:
                return None
            return FilterOperation(
                criterion_span,
                nearest_filter.span(),
                "UNKNOWN",
                "UNKNOWN",
                "EXPLICIT_FILTER_RESULT_NOT_PROVEN",
            )

        latest_end = max(item[1] for item in events)
        latest = [item for item in events if item[1] == latest_end]
        if len({item[2] for item in latest}) != 1:
            return FilterOperation(
                criterion_span,
                (latest[0][0], latest_end),
                "CONFLICTING",
                "UNKNOWN",
                "CONFLICTING_EXPLICIT_FILTER_RESULTS",
            )
        start, end, action, role, source = latest[-1]
        return FilterOperation(
            criterion_span,
            (start, end),
            role,
            action,
            source,
        )

    def _typed_filter_operation(
        self,
        category_id: str,
        text: str,
        facet_name: str,
        value_code: int,
    ) -> FilterOperation | None:
        """Bind filter criteria to an explicit KEEP/REMOVE result action.

        `필터/걸러` is not itself a polarity.  The criterion case and the
        result predicate must jointly prove whether the named value remains in
        or is removed from the candidate set.
        """
        if self.classifier.explicit_filter_result_guard:
            return self._explicit_filter_result_operation(
                category_id, text, facet_name, value_code
            )
        filter_matches = tuple(PROOF_FILTER_ACTION_PATTERN.finditer(text))
        if not filter_matches:
            return None
        all_occurrences = tuple(self.matcher.occurrences(category_id, text))
        occurrences = tuple(
            item
            for item in all_occurrences
            if (item.facet.facet_name, item.facet.value_code)
            == (facet_name, value_code)
        )
        if not occurrences:
            return None

        # Only the closest taxonomy key owns a bare filter head.  Repeated
        # mentions of the same key are treated as one criterion ledger.
        owned_filters = []
        for filter_match in filter_matches:
            nearest_distance = min(
                min(
                    abs(filter_match.start() - item.end),
                    abs(item.start - filter_match.end()),
                )
                for item in all_occurrences
            )
            key_distance = min(
                min(
                    abs(filter_match.start() - item.end),
                    abs(item.start - filter_match.end()),
                )
                for item in occurrences
            )
            if key_distance == nearest_distance and key_distance <= 48:
                owned_filters.append(filter_match)
        if not owned_filters:
            return None

        keep_evidence: list[tuple[int, int, str, str]] = []
        remove_evidence: list[tuple[int, int, str, str]] = []
        for occurrence in occurrences:
            tail_end = min(len(text), occurrence.end + 80)
            tail = text[occurrence.end:tail_end]

            criterion = re.match(
                r"\s*(?:(?:제형|형태|조건|기준|성분|항목|섭취\s*횟수)으로만|"
                r"(?:으로|로)(?:만)?|(?:을|를)?\s*기준으로)"
                r"[^.!?]{0,18}필터",
                tail,
            )
            if criterion:
                keep_evidence.append(
                    (
                        occurrence.end + criterion.start(),
                        occurrence.end + criterion.end(),
                        "INSTRUMENTAL_CRITERION",
                        "CASE_MARKED_FILTER_BY",
                    )
                )

            selected = re.match(
                r"[^.!?]{0,12}만[^.!?]{0,20}(?:남(?:기|겨|겼|길)|보여|선택|제한|한정)",
                tail,
            )
            if selected:
                keep_evidence.append(
                    (
                        occurrence.end + selected.start(),
                        occurrence.end + selected.end(),
                        "SELECTED_VALUE",
                        "EXPLICIT_KEEP_RESULT",
                    )
                )

            complement = re.match(
                r"[^.!?]{0,12}(?:아닌|이\s*아닌|이\s*외|외의|외에)[^.!?]{0,36}"
                r"(?:걸러내|필터)[^.!?]{0,24}(?:만\s*남(?:기|겨|겼|길)|이것만|그것만|해당[^.!?]{0,8}만)",
                tail,
            )
            if complement:
                keep_evidence.append(
                    (
                        occurrence.end + complement.start(),
                        occurrence.end + complement.end(),
                        "COMPLEMENT_ANCHOR",
                        "REMOVE_COMPLEMENT_RESULT",
                    )
                )

            removal = re.match(
                r"[^.!?]{0,36}(?:필터|걸러|거르)[^.!?]{0,28}"
                r"(?:제외|배제|빼|없애|숨겨|목록에서\s*빼)",
                tail,
            )
            if removal:
                remove_evidence.append(
                    (
                        occurrence.end + removal.start(),
                        occurrence.end + removal.end(),
                        "NAMED_OBJECT",
                        "EXPLICIT_REMOVE_RESULT",
                    )
                )

        # A later repeated `X만 남김` proves the anchor even when the
        # first occurrence owns the complement filter action.
        for occurrence in occurrences:
            selected_tail = text[occurrence.end:min(len(text), occurrence.end + 32)]
            selected = re.match(
                r"[^.!?]{0,8}만[^.!?]{0,16}남(?:기|겨|겼|길)", selected_tail
            )
            if selected:
                keep_evidence.append(
                    (
                        occurrence.end + selected.start(),
                        occurrence.end + selected.end(),
                        "SELECTED_VALUE",
                        "REPEATED_ANCHOR_KEEP",
                    )
                )

        criterion_start = min(item.start for item in occurrences)
        criterion_end = max(item.end for item in occurrences)
        if keep_evidence and remove_evidence:
            return FilterOperation(
                (criterion_start, criterion_end),
                (owned_filters[0].start(), owned_filters[-1].end()),
                "CONFLICTING",
                "UNKNOWN",
                "CONFLICTING_FILTER_RESULTS",
            )
        if keep_evidence:
            start, end, role, source = max(keep_evidence, key=lambda item: item[1])
            return FilterOperation(
                (criterion_start, criterion_end),
                (start, end),
                role,
                "KEEP",
                source,
            )
        if remove_evidence:
            start, end, role, source = max(remove_evidence, key=lambda item: item[1])
            return FilterOperation(
                (criterion_start, criterion_end),
                (start, end),
                role,
                "REMOVE",
                source,
            )
        return FilterOperation(
            (criterion_start, criterion_end),
            (owned_filters[0].start(), owned_filters[-1].end()),
            "UNKNOWN",
            "UNKNOWN",
            "FILTER_RESULT_NOT_PROVEN",
        )

    @staticmethod
    def _proof_set_operation(polarity: str, target_role: str, action: str) -> str:
        if target_role == "COMPLEMENT_OF":
            return "REMOVE_COMPLEMENT" if polarity == "MUST" else "SELECT_COMPLEMENT"
        if polarity == "EXCLUDE":
            return "REMOVE_NAMED"
        if polarity == "PREFER":
            return "RANK_NAMED"
        return "SELECT_NAMED"

    @staticmethod
    def _proof_evidence_offset(text: str, evidence: str) -> int | None:
        """Locate the exact evidence slice without inventing a fuzzy span."""
        start = text.rfind(evidence)
        return start if start >= 0 else None

    def _constraint_proof(
        self,
        category_id: str,
        text: str,
        constraint: FacetConstraint,
    ) -> ConstraintProof | None:
        """Return an auditable proof only for a locally bound final predicate.

        v0.26 may return a constraint from either an explicit PredicateFrame or
        the legacy clause classifier.  This gate independently reconstructs the
        evidence and rejects the result when the last explicit polarity differs,
        the predicate is not bound to the named facet, or an unresolved discourse
        operator occurs after the alleged final decision.
        """
        evidence = constraint.evidence_clause.strip()
        evidence_offset = self._proof_evidence_offset(text, evidence)
        if not evidence or evidence_offset is None:
            return None

        local_occurrences = tuple(
            item
            for item in self.matcher.occurrences(category_id, evidence)
            if (item.facet.facet_name, item.facet.value_code)
            == (constraint.facet_name, constraint.value_code)
        )
        if not local_occurrences:
            return None
        all_local_occurrences = tuple(self.matcher.occurrences(category_id, evidence))
        local_keys = {
            (item.facet.facet_name, item.facet.value_code)
            for item in all_local_occurrences
        }
        filter_operation = None
        if self.classifier.typed_filter_operation:
            filter_operation = self._typed_filter_operation(
                category_id,
                text,
                constraint.facet_name,
                constraint.value_code,
            )
            if (
                filter_operation is not None
                and filter_operation.result_action == "UNKNOWN"
            ):
                return None
        speaker_scope = None
        if self.classifier.speaker_scope_guard:
            speaker_scope = (
                self._request_provenance_scope(category_id, text)
                if self.classifier.request_provenance_firewall
                else self._speaker_scope(text)
            )

        # `X만 필터링/걸러` can mean either keep X or remove X depending on the
        # argument construction.  A lexical action head alone is not a proof.
        normalized_evidence = normalize(evidence)
        nominal_prohibition = bool(
            self.classifier.nominal_inclusion_prohibition_frame
            and re.search(r"포함(?:은|이|을|를)?\s*금지", normalized_evidence)
        )
        if (
            PROOF_FILTER_ACTION_PATTERN.search(normalized_evidence)
            and PROOF_SELECTED_PARTICLE_PATTERN.search(normalized_evidence)
            and filter_operation is None
            and not nominal_prohibition
        ):
            return None

        candidates: list[dict[str, object]] = []

        def add_candidate(
            *,
            polarity: str,
            start: int,
            end: int,
            source: str,
            argument_role: str,
            action: str,
            trusted: bool,
        ) -> None:
            if end <= start:
                return
            candidates.append({
                "polarity": polarity,
                "start": start,
                "end": end,
                "source": source,
                "argument_role": argument_role,
                "action": action,
                "trusted": trusted,
            })

        local_frames = self._build_predicate_frames(category_id, evidence)

        def selection_is_after_final_exclusion(
            signal: PredicateSignal,
            frames: tuple[PredicateFrame, ...],
            occurrences: tuple,
        ) -> bool:
            if (
                not self.classifier.occurrence_predicate_proof
                or signal.source not in {
                    "MORPH_SELECTION_HEAD",
                    "TYPED_EP_EF_ROLE_COMMITMENT",
                    "FRAME_GENERIC_SELECTION",
                }
            ):
                return False
            return any(
                frame.polarity == "EXCLUDE"
                and (frame.facet_name, frame.value_code)
                == (constraint.facet_name, constraint.value_code)
                and frame.argument_end <= signal.position
                and not any(
                    item.start > frame.argument_end
                    and (item.facet.facet_name, item.facet.value_code)
                    == (constraint.facet_name, constraint.value_code)
                    for item in occurrences
                )
                for frame in frames
            )

        def occurrence_bound_to_signal(
            signal: PredicateSignal,
            occurrences: tuple,
        ):
            if (
                self.classifier.occurrence_predicate_proof
                and signal.source in {"REGEX_MUST", "MORPH_RANK_MARKER"}
            ):
                following = [
                    item
                    for item in occurrences
                    if 0 <= item.start - signal.position <= 8
                ]
                if following:
                    return min(following, key=lambda item: (item.start, item.end))
            preceding = [
                item for item in occurrences if item.start <= signal.position
            ]
            if not preceding:
                return None
            return max(preceding, key=lambda item: (item.start, item.end))

        for frame in local_frames:
            if (frame.facet_name, frame.value_code) != (
                constraint.facet_name,
                constraint.value_code,
            ):
                continue
            add_candidate(
                polarity=frame.polarity,
                start=frame.argument_start,
                end=frame.argument_end,
                source=f"PREDICATE_FRAME:{frame.action}:{frame.target_role}",
                argument_role=frame.target_role,
                action=frame.action,
                trusted=(
                    frame.modality == "COMMITTED"
                    and frame.temporal == "NOW"
                    and not frame.negated
                    and (
                        frame.target_role == "COMPLEMENT_OF"
                        or any(
                            item.end < frame.argument_end
                            for item in local_occurrences
                        )
                    )
                ),
            )

        signals = self._framed_predicate_signals(evidence)
        for signal in signals:
            if signal.polarity is None:
                continue
            if selection_is_after_final_exclusion(
                signal, local_frames, all_local_occurrences
            ):
                continue
            bound = occurrence_bound_to_signal(signal, all_local_occurrences)
            if bound is None:
                continue
            if (bound.facet.facet_name, bound.facet.value_code) != (
                constraint.facet_name,
                constraint.value_code,
            ):
                continue
            add_candidate(
                polarity=signal.polarity,
                start=signal.start,
                end=signal.position,
                source=signal.source,
                argument_role="NAMED_VALUE",
                action=(
                    "REMOVE" if signal.polarity == "EXCLUDE"
                    else "RANK" if signal.polarity == "PREFER"
                    else "SELECT"
                ),
                trusted=(
                    signal.modality == "COMMITTED"
                    and signal.source != "FRAME_GENERIC_SELECTION"
                ),
            )

        matched_values = tuple(item.facet.value for item in all_local_occurrences)
        classification = self.classifier.classify(evidence, matched_values)
        marker_types = {
            kind for kind, markers in classification.matched_markers.items() if markers
        }
        # A marker is proof only when it has one unambiguous polarity and the
        # evidence slice refers to a single taxonomy key.
        if len(marker_types) == 1 and len(local_keys) == 1:
            marker_type = next(iter(marker_types))
            for marker in classification.matched_markers[marker_type]:
                marker_start = normalized_evidence.rfind(normalize(marker))
                if marker_start < 0:
                    continue
                marker_end = marker_start + len(normalize(marker))
                add_candidate(
                    polarity=marker_type,
                    start=marker_start,
                    end=marker_end,
                    source=f"CLASSIFIER_MARKER:{marker}",
                    argument_role="NAMED_VALUE",
                    action=(
                        "REMOVE" if marker_type == "EXCLUDE"
                        else "RANK" if marker_type == "PREFER"
                        else "SELECT"
                    ),
                    trusted=classification.constraint_type == marker_type,
                )

        # An otherwise unmarked direct command is allowed only when morphology
        # identifies a finalized action and exactly one facet key is in scope.
        if (
            constraint.constraint_type == "MUST"
            and len(local_keys) == 1
            and self.classifier.is_morphological_direct_request(evidence)
        ):
            direct = [
                signal
                for signal in signals
                if signal.modality == "COMMITTED"
                and signal.source in {"REGEX_DIRECT", "MORPH_SELECTION_HEAD"}
            ]
            if direct:
                signal = direct[-1]
                add_candidate(
                    polarity="MUST",
                    start=signal.start,
                    end=signal.position,
                    source=f"DIRECT_REQUEST:{signal.source}",
                    argument_role="NAMED_VALUE",
                    action="SELECT",
                    trusted=True,
                )

        # Evidence clauses from v0.26 can end at an earlier frame even when a
        # later same-facet decision or a typed coreference carries the real final
        # predicate.  Promote local coordinates to document coordinates, then
        # inspect the full utterance without borrowing a predicate from a nearer
        # different facet.
        for item in candidates:
            item["start"] = evidence_offset + int(item["start"])
            item["end"] = evidence_offset + int(item["end"])

        full_occurrences = tuple(self.matcher.occurrences(category_id, text))
        full_frames = self._build_predicate_frames(category_id, text)
        if evidence != text:
            for frame in full_frames:
                if (frame.facet_name, frame.value_code) != (
                    constraint.facet_name,
                    constraint.value_code,
                ):
                    continue
                matching_occurrences = [
                    item
                    for item in full_occurrences
                    if (item.facet.facet_name, item.facet.value_code)
                    == (constraint.facet_name, constraint.value_code)
                    and item.start <= frame.argument_end
                ]
                if not matching_occurrences:
                    continue
                add_candidate(
                    polarity=frame.polarity,
                    start=frame.argument_start,
                    end=frame.argument_end,
                    source=f"PREDICATE_FRAME:{frame.action}:{frame.target_role}",
                    argument_role=frame.target_role,
                    action=frame.action,
                    trusted=(
                        frame.modality == "COMMITTED"
                        and frame.temporal == "NOW"
                        and not frame.negated
                        and (
                            frame.target_role == "COMPLEMENT_OF"
                            or any(
                                item.end < frame.argument_end
                                for item in matching_occurrences
                            )
                        )
                    ),
                )

            full_signals = self._framed_predicate_signals(text)
            for signal in full_signals:
                if signal.polarity is None:
                    continue
                if selection_is_after_final_exclusion(
                    signal, full_frames, full_occurrences
                ):
                    continue
                bound = occurrence_bound_to_signal(signal, full_occurrences)
                if bound is None:
                    continue
                if (bound.facet.facet_name, bound.facet.value_code) != (
                    constraint.facet_name,
                    constraint.value_code,
                ):
                    continue
                add_candidate(
                    polarity=signal.polarity,
                    start=signal.start,
                    end=signal.position,
                    source=signal.source,
                    argument_role=(
                        "COREFERENCE"
                        if TYPED_COREFERENCE_PATTERN.search(
                            normalize(text[bound.end:signal.position])
                        )
                        else "NAMED_VALUE"
                    ),
                    action=(
                        "REMOVE" if signal.polarity == "EXCLUDE"
                        else "RANK" if signal.polarity == "PREFER"
                        else "SELECT"
                    ),
                    trusted=(
                        signal.modality == "COMMITTED"
                        and signal.source != "FRAME_GENERIC_SELECTION"
                    ),
                )

        final_action_evidence = None
        if self.classifier.typed_action_evidence:
            matching_action_evidence = [
                item
                for item in self._typed_occurrence_action_evidence(category_id, text)
                if (item.facet_name, item.value_code)
                == (constraint.facet_name, constraint.value_code)
            ]
            if matching_action_evidence:
                last_occurrence_span = max(
                    (
                        (item.start, item.end)
                        for item in self._canonical_occurrences(category_id, text)
                        if (item.facet.facet_name, item.facet.value_code)
                        == (constraint.facet_name, constraint.value_code)
                    ),
                    default=None,
                )
                final_items = [
                    item
                    for item in matching_action_evidence
                    if item.taxonomy_span == last_occurrence_span
                ]
                if final_items:
                    final_action_evidence = max(
                        final_items, key=lambda item: item.predicate_span[1]
                    )
                    action_start, action_end = final_action_evidence.predicate_span
                    if final_action_evidence.action == "REMOVE":
                        if (
                            self.classifier.nominal_inclusion_prohibition_frame
                            and final_action_evidence.source
                            == "ACTION_OCCURRENCE_BOUND_INCLUSION"
                            and "금지" in normalize(text[action_start:action_end])
                        ):
                            for item in candidates:
                                if (
                                    str(item["polarity"]) in {"MUST", "PREFER"}
                                    and int(item["end"]) <= action_end
                                ):
                                    item["polarity"] = "EXCLUDE"
                                    item["source"] = (
                                        "NOMINAL_PROHIBITION:"
                                        f"{final_action_evidence.source}"
                                    )
                        candidates = [
                            item
                            for item in candidates
                            if not (
                                str(item["polarity"]) in {"MUST", "PREFER"}
                                and int(item["end"]) > action_end
                            )
                        ]
                    else:
                        for item in candidates:
                            if (
                                str(item["polarity"]) in {"MUST", "PREFER"}
                                and final_action_evidence.taxonomy_span[1]
                                <= int(item["end"]) <= action_end
                            ):
                                item["polarity"] = final_action_evidence.polarity
                                item["source"] = (
                                    "OCCURRENCE_STRENGTH:"
                                    f"{final_action_evidence.source}"
                                )
                    add_candidate(
                        polarity=final_action_evidence.polarity,
                        start=action_start,
                        end=action_end,
                        source=final_action_evidence.source,
                        argument_role="NAMED_VALUE",
                        action=final_action_evidence.action,
                        trusted=True,
                    )

        if filter_operation is not None:
            polarity = (
                "MUST"
                if filter_operation.result_action == "KEEP"
                else "EXCLUDE"
            )
            target_role = (
                "COMPLEMENT_OF"
                if filter_operation.case_role == "COMPLEMENT_ANCHOR"
                else "NAMED_VALUE"
            )
            candidates = []
            add_candidate(
                polarity=polarity,
                start=filter_operation.predicate_span[0],
                end=filter_operation.predicate_span[1],
                source=f"TYPED_FILTER:{filter_operation.source}",
                argument_role=target_role,
                action="SELECT" if polarity == "MUST" else "REMOVE",
                trusted=True,
            )

        if not candidates:
            return None

        # The latest explicit polarity is authoritative.  A proof matching an
        # earlier request cannot validate a different v0.26 final result.
        latest_end = max(int(item["end"]) for item in candidates)
        latest = [item for item in candidates if int(item["end"]) == latest_end]
        if len({str(item["polarity"]) for item in latest}) != 1:
            return None
        chosen = max(latest, key=lambda item: (bool(item["trusted"]), int(item["start"])))
        if (
            not bool(chosen["trusted"])
            or str(chosen["polarity"]) != constraint.constraint_type
        ):
            return None

        last_taxonomy_end = max(
            item.end
            for item in full_occurrences
            if (item.facet.facet_name, item.facet.value_code)
            == (constraint.facet_name, constraint.value_code)
        )
        # With repeated mentions, an early marker cannot prove the final mention.
        # This blocks an abandoned `X 말고 ...` from validating a later `X만 ...`.
        if len(local_occurrences) > 1 and int(chosen["end"]) < last_taxonomy_end:
            return None

        predicate_start = int(chosen["start"])
        predicate_end = int(chosen["end"])
        taxonomy_candidates = [
            item
            for item in full_occurrences
            if (item.facet.facet_name, item.facet.value_code)
            == (constraint.facet_name, constraint.value_code)
        ]
        if not taxonomy_candidates:
            return None
        # Modality commonly precedes its value (`가능하면 분말로`).
        # Bind to the closest occurrence on either side of the predicate instead
        # of assuming that every valid predicate follows the taxonomy surface.
        def span_distance(item) -> tuple[int, int]:
            if item.end < predicate_start:
                distance = predicate_start - item.end
            elif item.start > predicate_end:
                distance = item.start - predicate_end
            else:
                distance = 0
            return (distance, -item.start)

        taxonomy = min(taxonomy_candidates, key=span_distance)
        taxonomy_start = taxonomy.start
        taxonomy_end = taxonomy.end

        # A surface such as `X만 제외하고 보여` contains a positive
        # selection shell and an explicit REMOVE head in the very same argument
        # span.  The legacy classifier may choose either reading; that conflict
        # is precisely the kind of missing proof the gate must abstain on.
        if filter_operation is None:
            competing_polarities = set()
            for signal in self._framed_predicate_signals(text):
                if (
                    signal.polarity is None
                    or signal.modality != "COMMITTED"
                    or not taxonomy_end <= signal.position <= predicate_end
                ):
                    continue
                polarity = signal.polarity
                if (
                    final_action_evidence is not None
                    and final_action_evidence.action != "REMOVE"
                    and polarity in {"MUST", "PREFER"}
                    and signal.position <= final_action_evidence.predicate_span[1]
                ):
                    polarity = final_action_evidence.polarity
                elif (
                    self.classifier.typed_negated_removal_final_action
                    and final_action_evidence is not None
                    and final_action_evidence.action != "REMOVE"
                    and polarity == "EXCLUDE"
                    and signal.position <= final_action_evidence.predicate_span[1]
                    and re.search(
                        r"(?:빼|제외|배제|제거)[^.!?]{0,8}"
                        r"(?:지\s*않|지\s*말)",
                        normalize(
                            text[
                                taxonomy_end:
                                final_action_evidence.predicate_span[1]
                            ]
                        ),
                    )
                ):
                    polarity = final_action_evidence.polarity
                elif (
                    final_action_evidence is not None
                    and final_action_evidence.action == "REMOVE"
                    and polarity in {"MUST", "PREFER"}
                    and signal.position <= final_action_evidence.predicate_span[1]
                ):
                    polarity = "EXCLUDE"
                competing_polarities.add(polarity)
            if competing_polarities - {constraint.constraint_type}:
                return None

        next_other_start = min(
            (
                item.start
                for item in full_occurrences
                if item.start > predicate_end
                and (item.facet.facet_name, item.facet.value_code)
                != (constraint.facet_name, constraint.value_code)
            ),
            default=len(text),
        )
        proof_context_end = max(predicate_end, next_other_start)

        normalized_text = normalize(text)
        unresolved_matches = [
            match
            for pattern in PROOF_UNRESOLVED_MODALITY_PATTERNS
            for match in pattern.finditer(normalized_text)
        ]
        if self.classifier.token_aligned_unresolved_modality:
            token_boundaries = {0, len(normalized_text)}
            for token in self.matcher.kiwi.tokenize(normalized_text):
                token_boundaries.add(token.start)
                token_boundaries.add(token.start + token.len)
            unresolved_matches = [
                match
                for match in unresolved_matches
                if match.start() in token_boundaries and match.end() in token_boundaries
            ]
        if unresolved_matches:
            last_unresolved_end = max(match.end() for match in unresolved_matches)
            if predicate_end <= last_unresolved_end:
                return None
            restored_by_typed_occurrence = bool(
                final_action_evidence is not None
                and final_action_evidence.taxonomy_span[0] >= last_unresolved_end
            )
            if (
                not restored_by_typed_occurrence
                and not PROOF_CURRENT_MARKER_PATTERN.search(
                    normalized_text[last_unresolved_end:proof_context_end]
                )
            ):
                return None

        # A later tentative/cancelled predicate invalidates an earlier proof.
        all_signals = self._framed_predicate_signals(text)
        later_unresolved_signal = any(
            signal.modality != "COMMITTED"
            and predicate_end <= signal.position <= proof_context_end
            for signal in all_signals
        )
        if later_unresolved_signal:
            return None

        argument_role = str(chosen["argument_role"])
        action = str(chosen["action"])
        return ConstraintProof(
            taxonomy_span=(taxonomy_start, taxonomy_end),
            predicate_span=(predicate_start, predicate_end),
            argument_role=argument_role,
            set_operation=self._proof_set_operation(
                constraint.constraint_type, argument_role, action
            ),
            polarity_source=str(chosen["source"]),
            modality_scope="COMMITTED_FINAL",
            final_state_order=predicate_end,
            filter_operation=filter_operation,
            speaker_scope=speaker_scope,
        )

    def _extract_with_proof_carrying_constraint_gate(
        self,
        category_id: str,
        text: str,
        baseline: ExtractionResult | None = None,
    ) -> ExtractionResult:
        if baseline is None:
            baseline = self._extract_with_unified_predicate_frame_ledger(
                category_id, text
            )
        baseline = self._apply_typed_occurrence_evidence(
            category_id, text, baseline
        )
        if baseline.status != "PARSED":
            return baseline

        proven: list[FacetConstraint] = []
        missing: list[str] = []
        for constraint in baseline.constraints:
            proof = self._constraint_proof(category_id, text, constraint)
            if proof is None:
                missing.append(
                    f"PROOF_MISSING:{constraint.facet_name}:{constraint.value_code}"
                )
                continue
            proven.append(FacetConstraint(
                facet_name=constraint.facet_name,
                value_code=constraint.value_code,
                value=constraint.value,
                constraint_type=constraint.constraint_type,
                evidence_clause=constraint.evidence_clause,
                proof=proof,
            ))
        if missing:
            return ExtractionResult("REVIEW", (), tuple(missing), baseline.clauses)
        return ExtractionResult("PARSED", tuple(proven), (), baseline.clauses)

    def _extract_with_typed_filter_speaker_scope(
        self,
        category_id: str,
        text: str,
    ) -> ExtractionResult:
        speaker_scope = (
            self._request_provenance_scope(category_id, text)
            if self.classifier.request_provenance_firewall
            else self._speaker_scope(text)
        )
        if (
            self.classifier.speaker_scope_guard
            and (
                speaker_scope.owner != "USER"
                or speaker_scope.acceptance != "ACCEPTED"
            )
        ):
            return ExtractionResult(
                "REVIEW",
                (),
                (
                    f"SPEAKER_SCOPE:{speaker_scope.owner}:"
                    f"{speaker_scope.acceptance}",
                ),
                (text,),
            )

        if (
            self.classifier.reported_segment_user_tail
            and speaker_scope.user_tail_span is not None
        ):
            tail_start, tail_end = speaker_scope.user_tail_span
            tail_result = self._extract_with_typed_filter_speaker_scope(
                category_id, text[tail_start:tail_end]
            )
            if tail_result.status != "PARSED":
                return ExtractionResult(
                    "REVIEW",
                    (),
                    tail_result.warnings,
                    (text,),
                )
            return self._offset_tail_result(
                tail_result,
                tail_start,
                speaker_scope,
                text,
            )

        if self.classifier.minimal_proven_user_span:
            required_keys = {
                (item.facet.facet_name, item.facet.value_code)
                for item in self.matcher.occurrences(category_id, text)
            }
            if required_keys:
                minimal_end = self._minimal_proven_span_end(
                    category_id, text, required_keys
                )
                if minimal_end is not None and minimal_end < len(text):
                    return self._extract_with_typed_filter_speaker_scope(
                        category_id, text[:minimal_end]
                    )

        baseline = self._extract_with_unified_predicate_frame_ledger(
            category_id, text
        )
        if not self.classifier.typed_filter_operation:
            return self._extract_with_proof_carrying_constraint_gate(
                category_id, text, baseline
            )

        operations: dict[tuple[str, int], FilterOperation] = {}
        occurrences = tuple(self.matcher.occurrences(category_id, text))
        for occurrence in occurrences:
            key = (occurrence.facet.facet_name, occurrence.facet.value_code)
            if key in operations:
                continue
            operation = self._typed_filter_operation(
                category_id, text, key[0], key[1]
            )
            if operation is not None:
                operations[key] = operation

        if any(item.result_action == "UNKNOWN" for item in operations.values()):
            return ExtractionResult(
                "REVIEW", (), ("FILTER_OPERATION_UNKNOWN",), (text,)
            )
        if not operations:
            return self._extract_with_proof_carrying_constraint_gate(
                category_id, text, baseline
            )
        if baseline.status != "PARSED":
            if not self.classifier.explicit_filter_result_guard:
                return baseline
            operation_keys = set(operations)
            occurrence_keys = {
                (item.facet.facet_name, item.facet.value_code)
                for item in occurrences
            }
            if operation_keys != occurrence_keys:
                return baseline
            facets_by_key = {
                (item.facet.facet_name, item.facet.value_code): item.facet
                for item in occurrences
            }
            baseline = ExtractionResult(
                "PARSED",
                tuple(
                    FacetConstraint(
                        facet_name=facets_by_key[key].facet_name,
                        value_code=facets_by_key[key].value_code,
                        value=facets_by_key[key].value,
                        constraint_type=(
                            "MUST"
                            if operation.result_action == "KEEP"
                            else "EXCLUDE"
                        ),
                        evidence_clause=text,
                    )
                    for key, operation in operations.items()
                ),
                (),
                (text,),
            )

        rewritten = []
        for constraint in baseline.constraints:
            operation = operations.get(
                (constraint.facet_name, constraint.value_code)
            )
            constraint_type = constraint.constraint_type
            if operation is not None:
                constraint_type = (
                    "MUST" if operation.result_action == "KEEP" else "EXCLUDE"
                )
            rewritten.append(FacetConstraint(
                facet_name=constraint.facet_name,
                value_code=constraint.value_code,
                value=constraint.value,
                constraint_type=constraint_type,
                evidence_clause=constraint.evidence_clause,
            ))
        typed_baseline = ExtractionResult(
            "PARSED", tuple(rewritten), baseline.warnings, baseline.clauses
        )
        return self._extract_with_proof_carrying_constraint_gate(
            category_id, text, typed_baseline
        )

    def extract(self, category_id: str, text: str) -> ExtractionResult:
        ambiguous_removals = self._ambiguous_negated_removal_targets(
            category_id, text
        )
        if ambiguous_removals:
            return ExtractionResult(
                "REVIEW",
                (),
                tuple(
                    f"AMBIGUOUS_NEGATED_REMOVAL_TARGET:{facet_name}:{value_code}"
                    for facet_name, value_code in ambiguous_removals
                ),
                (text,),
            )
        negative_comparatives = self._negative_comparative_state_targets(
            category_id, text
        )
        if negative_comparatives:
            return ExtractionResult(
                "REVIEW",
                (),
                tuple(
                    f"NEGATIVE_COMPARATIVE_STATE_UNSUPPORTED:{facet_name}:{value_code}"
                    for facet_name, value_code in negative_comparatives
                ),
                (text,),
            )
        negative_preferences = self._negative_preference_evidence(
            category_id, text
        )
        if negative_preferences:
            return ExtractionResult(
                "REVIEW",
                (),
                tuple(
                    "NEGATIVE_PREFERENCE_UNSUPPORTED:"
                    f"{item.facet_name}:{item.value_code}"
                    for item in negative_preferences
                ),
                (text,),
            )
        if (
            self.classifier.typed_filter_operation
            or self.classifier.speaker_scope_guard
        ):
            return self._extract_with_typed_filter_speaker_scope(category_id, text)
        if self.classifier.proof_carrying_constraint_gate:
            return self._extract_with_proof_carrying_constraint_gate(category_id, text)
        if self.classifier.unified_predicate_frame_ledger:
            return self._extract_with_unified_predicate_frame_ledger(category_id, text)
        if self.classifier.predicate_frame_scoping:
            framed = self._extract_with_predicate_frames(category_id, text)
            if framed is not None:
                return framed
        if self.classifier.predicate_span_event_ordering:
            return self._extract_with_predicate_event_ordering(category_id, text)
        if self.classifier.facet_event_state_machine:
            return self._extract_with_event_state_machine(category_id, text)
        normalized = normalize(text)
        final_commitment_state = self._final_commitment_state(category_id, text)
        if final_commitment_state == "NON_COMMITTED":
            return ExtractionResult("REVIEW", (), ("NON_COMMITTED_FINAL_STATE",), (text,))
        if self._is_reported_non_user_context(normalized):
            return ExtractionResult("REVIEW", (), ("REPORTED_OR_NON_USER_CONTEXT",), (text,))
        if (
            self.classifier.is_non_final_selection_context(normalized)
            and final_commitment_state != "RESTORED"
            and not self.classifier.is_positive_double_negative(normalized)
            and not any(
                pattern.search(normalized)
                for pattern in self.classifier.positive_double_negative_priority_regexes
            )
        ):
            return ExtractionResult("REVIEW", (), ("NON_FINAL_SELECTION_CONTEXT",), (text,))
        if (
            any(pattern in normalized for pattern in ACCEPTANCE_PATTERNS)
            and any(pattern in normalized for pattern in AVERSION_PATTERNS)
        ):
            return ExtractionResult("REVIEW", (), ("ACCEPTANCE_AVERSION_CONTRAST",), (text,))
        if "상관없" in normalized and normalized.count("든") >= 2:
            occurrences = self.matcher.occurrences(category_id, text)
            distinct_values = {
                (item.facet.facet_name, item.facet.value_code)
                for item in occurrences
            }
            if len(distinct_values) > 1:
                return ExtractionResult("REVIEW", (), ("MULTI_VALUE_ACCEPTANCE_SCOPE",), (text,))
        if any(pattern in normalized for pattern in ALTERNATIVE_PATTERNS):
            return ExtractionResult("REVIEW", (), ("ALTERNATIVE_VALUE_SCOPE",), (text,))
        pronoun_exclusion = "그거 아니면" in normalized and any(
            marker in normalized for marker in self.classifier.rules.get("EXCLUDE", ())
        )
        if (
            "아니면" in normalized
            and not pronoun_exclusion
            and not self.classifier.is_positive_double_negative(normalized)
        ):
            return ExtractionResult("REVIEW", (), ("ALTERNATIVE_VALUE_SCOPE",), (text,))
        if any(pattern in normalized for pattern in SCOPE_REVIEW_PATTERNS):
            return ExtractionResult("REVIEW", (), ("UNSUPPORTED_RELATIONAL_SCOPE",), (text,))
        if any(pattern in normalized for pattern in self.classifier.review_patterns):
            return ExtractionResult("REVIEW", (), ("KNOWN_AMBIGUOUS_PATTERN",), (text,))

        base_clauses = self.split_clauses(category_id, text)
        explicitly_split = tuple(
            expanded
            for clause in base_clauses
            for expanded in self._split_explicit_multi_value_clause(category_id, clause)
        )
        clauses = tuple(
            scoped
            for clause in explicitly_split
            for scoped in self._split_candidate_pool_scope(category_id, clause)
        )
        for clause in clauses:
            if any(pattern in normalize(clause) for pattern in FACET_RELATIONAL_PATTERNS):
                if self.matcher.match(category_id, clause).facets:
                    return ExtractionResult(
                        "REVIEW",
                        (),
                        ("UNSUPPORTED_RELATIONAL_SCOPE",),
                        clauses,
                    )
        constraints = []
        warnings = []
        meaningful_clause_count = 0
        for clause in clauses:
            if (
                final_commitment_state == "RESTORED"
                and any(pattern.search(normalize(clause)) for pattern in NON_COMMITTED_FINAL_PATTERNS)
            ):
                continue
            if any(pattern in normalize(clause) for pattern in NO_REQUIREMENT_PATTERNS):
                continue
            meaningful_clause_count += 1
            facet_result = self.matcher.match(category_id, clause)
            if facet_result.warnings:
                warnings.extend(f"{warning}: {clause}" for warning in facet_result.warnings)
                continue
            if not facet_result.facets:
                continue
            classification = self.classifier.classify(
                clause,
                tuple(facet.value for facet in facet_result.facets),
            )
            relation_overrides = {
                (facet.facet_name, facet.value_code): self._relation_override(
                    category_id,
                    clause,
                    facet.facet_name,
                    facet.value_code,
                )
                for facet in facet_result.facets
            }
            if (
                classification.constraint_type == "REVIEW"
                and not any(relation_overrides.values())
            ):
                warnings.append(f"{classification.reason}: {clause}")
                continue
            for facet in facet_result.facets:
                constraint_type = relation_overrides[(facet.facet_name, facet.value_code)]
                if constraint_type is None:
                    if classification.constraint_type == "REVIEW":
                        warnings.append(
                            f"{classification.reason}: {facet.value} in {clause}"
                        )
                        continue
                    constraint_type = classification.constraint_type
                constraints.append(FacetConstraint(
                    facet_name=facet.facet_name,
                    value_code=facet.value_code,
                    value=facet.value,
                    constraint_type=constraint_type,
                    evidence_clause=clause,
                ))

        unique = {}
        for constraint in constraints:
            key = (constraint.facet_name, constraint.value_code, constraint.constraint_type)
            unique[key] = constraint
        final_constraints = tuple(unique.values())
        if not meaningful_clause_count:
            status = "NONE"
        elif warnings:
            status = "REVIEW"
        elif final_constraints:
            status = "PARSED"
        else:
            status = "REVIEW"
            warnings.append("NO_FACET_CONSTRAINT_EXTRACTED")
        return ExtractionResult(status, final_constraints, tuple(warnings), clauses)
