CREATE TABLE `BrandpayPayMethod` (
	`id`	BIGINT	NOT NULL,
	`member_id`	BIGINT	NOT NULL,
	`method_key`	VARCHAR(255)	NOT NULL,
	`provider_code`	VARCHAR(30)	NOT NULL,
	`masked_number`	VARCHAR(30)	NOT NULL	COMMENT '저장할때 앞에서 4자리만 저장',
	`type`	VARCHAR(30)	NULL	COMMENT '카드, 계좌',
	`is_default`	BOOL	NOT NULL,
	`status`	VARCHAR(30)	NOT NULL,
	`created_at`	TIMESTAMP	NOT NULL
);

CREATE TABLE `SellerKey` (
	`seller_id`	BIGINT	NOT NULL,
	`seller_key`	VARCHAR(20)	NOT NULL
);

CREATE TABLE `notification_opt_out` (
	`type`	VARCHAR(40)	NOT NULL,
	`member_id`	BIGINT	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `product_catalog` (
	`id`	BIGINT	NOT NULL,
	`name`	VARCHAR(100)	NOT NULL,
	`category_id`	BIGINT	NOT NULL,
	`spec_summary`	VARCHAR(500)	NULL,
	`list_price`	INTEGER	NULL,
	`thumbnail_url`	VARCHAR(255)	NOT NULL,
	`description`	TEXT	NULL,
	`status`	VARCHAR(20)	NOT NULL	DEFAULT 'ACTIVE',
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `SellerPayoutAccount` (
	`id`	BIGINT	NOT NULL,
	`seller_id`	BIGINT	NOT NULL,
	`pg_seller_key`	VARCHAR(35)	NULL	COMMENT 'PG사에 판매자를 등록하면 PG사가 발급',
	`businessType`	VARCHAR(30)	NULL	COMMENT 'INDIVIDUAL(개인), INDIVIDUAL_BUSINESS (개인사업자), CORPORATE(법인사업자)',
	`status`	VARCHAR(30)	NULL	COMMENT '- APPROVAL_REQUIRED: 지급대행이 불가능한 상태입니다. 개인 및 개인사업자 셀러 등록 직후의 상태이며, 본인인증이 필요합니다.

- PARTIALLY_APPROVED: 일주일 동안 1천만원까지 지급대행이 가능한 상태입니다. 등록 직후의 법인사업자 셀러 또는 본인인증을 완료한 개인 및 개인사업자 셀러의 상태입니다.

- KYC_REQUIRED: 지급대행이 불가능한 상태입니다. 일주일 동안 1천만원을 초과하는 금액을 지급 요청하면 셀러는 해당 상태로 변경됩니다. 셀러가 KYC 심사를 완료해야 합니다.

- APPROVED: 금액 제한 없이 지급대행이 가능한 상태입니다. KYC 심사가 정상적으로 완료된 셀러의 상태입니다.',
	`bankCode`	VARCHAR(10)	NULL,
	`bank_account`	VARCHAR(50)	NULL,
	`depositor_name`	VARCHAR(50)	NULL
);

CREATE TABLE `demand_board` (
	`id`	BIGINT	NOT NULL,
	`catalog_id`	BIGINT	NOT NULL,
	`participant_count`	INTEGER	NOT NULL	DEFAULT 0,
	`price_min`	INTEGER	NULL,
	`price_max`	INTEGER	NULL,
	`status`	VARCHAR(20)	NOT NULL	DEFAULT 'OPEN',
	`judged_at`	TIMESTAMPTZ	NULL,
	`sale_end_at`	TIMESTAMPTZ	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `PaymentsWebhock` (
	`id`	BIGINT	NOT NULL,
	`transmission_id`	VARCHAR(255)	NULL,
	`event_type`	VARCHAR(50)	NULL,
	`toss_created_at`	TIMESTAMP	NULL,
	`customer_key`	VARCHAR(50)	NULL,
	`method_key`	VARCHAR(255)	NULL,
	`payment_key`	VARCHAR(200)	NULL,
	`order_id`	VARCHAR(64)	NULL,
	`payload`	JSON	NULL,
	`received_at`	TIMESTAMP	NULL,
	`processed_at`	TIMESTAMP	NULL
);

CREATE TABLE `product_award_evaluation` (
	`id`	BIGINT	NOT NULL,
	`product_id`	BIGINT	NOT NULL,
	`demand_board_id`	BIGINT	NOT NULL,
	`score`	NUMERIC(5,4)	NULL,
	`reason`	TEXT	NULL,
	`is_awarded`	BOOLEAN	NOT NULL,
	`judged_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `BrandPayToken` (
	`member_id`	BIGINT	NOT NULL,
	`access_token`	TEXT	NULL,
	`refresh_token`	TEXT	NULL,
	`access_token_expires_at`	TIMESTAMPTZ	NULL
);

CREATE TABLE `CustomerKey` (
	`member_id`	BIGINT	NOT NULL,
	`customer_key`	VARCHAR(50)	NOT NULL
);

CREATE TABLE `notification` (
	`id`	BIGINT	NOT NULL,
	`notification_event_id`	BIGINT	NOT NULL,
	`member_id`	BIGINT	NOT NULL,
	`is_read`	BOOLEAN	NOT NULL	DEFAULT FALSE,
	`read_at`	TIMESTAMPTZ	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `demand` (
	`id`	BIGINT	NOT NULL,
	`demand_board_id`	BIGINT	NULL,
	`member_id`	BIGINT	NOT NULL,
	`catalog_id`	BIGINT	NOT NULL,
	`pay_method_id`	BIGINT	NOT NULL,
	`desired_price_max`	INTEGER	NULL,
	`desired_price_min`	INTEGER	NULL,
	`desire_end_at`	TIMESTAMPTZ	NULL,
	`quantity`	INTEGER	NULL,
	`extra_requirement`	VARCHAR(200)	NULL,
	`is_substitutable`	BOOLEAN	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`status`	VARCHAR(20)	NULL,
	`label`	VARCHAR(200)	NULL,
	`processed_at`	TIMESTAMPTZ	NULL
);

CREATE TABLE `Orders` (
	`id`	BIGINT	NOT NULL,
	`brandpay_id`	BIGINT	NOT NULL,
	`customer_id`	BIGINT	NOT NULL,
	`group_buy_id`	BIGINT	NOT NULL,
	`order_no`	VARCHAR(64)	NOT NULL	COMMENT '영문 대소문자, 숫자, 특수문자 -, _로 이루어진 6자 이상 64자 이하의 문자열',
	`total_amount`	INTEGER	NOT NULL,
	`product_id`	BIGINT	NULL,
	`product_name`	VARCHAR(100)	NOT NULL,
	`sum`	INTEGER	NOT NULL	COMMENT '구매하는 상품의 수량',
	`price`	INTEGER	NOT NULL	COMMENT '상품의 개당 가격',
	`shipping_name`	VARCHAR(50)	NOT NULL,
	`phone_number`	TEXT	NULL,
	`shipping_number`	TEXT	NOT NULL,
	`order_status`	VARCHAR(30)	NOT NULL,
	`seller_id`	BIGINT	NOT NULL,
	`business_name`	VARCHAR(50)	NOT NULL,
	`zipcode`	VARCHAR(5)	NOT NULL,
	`address`	VARCHAR(255)	NOT NULL,
	`address_detail`	VARCHAR(100)	NOT NULL,
	`image_url`	VARCHAR(255)	NULL,
	`updated_at`	TIMESTAMPTZ	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL,
	`shipping_memo`	VARCHAR(255)	NULL,
	`demand_id`	BIGINT	NOT NULL
);

CREATE TABLE `outbox_event` (
	`id`	BIGINT	NOT NULL,
	`event_type`	ENUM	NOT NULL	COMMENT 'GROUP_BUY_JUDGMENT_SCHEDULED (공구 판정을 에약)',
	`aggregate_id`	BIGINT	NOT NULL,
	`scheduled_at`	TIMESTAMP	NOT NULL,
	`status`	ENUM	NOT NULL	COMMENT 'PENDING, // 외부 저장소 발행 대기 또는 실패 후 재시도 대기
    PUBLISHED // 외부 저장소 발행 완료',
	`retry_count`	TIMESTAMP	NOT NULL	COMMENT '재시도 시간',
	`next_attempt_at`	TIMESTAMP	NOT NULL,
	`published_at`	TIMESTAMP	NULL
);

CREATE TABLE `product` (
	`id`	BIGINT	NOT NULL,
	`catalog_id`	BIGINT	NOT NULL,
	`demand_board_id`	BIGINT	NOT NULL,
	`seller_id`	BIGINT	NOT NULL,
	`thumbnail_url`	VARCHAR(255)	NULL,
	`unit_price`	INTEGER	NOT NULL,
	`shipping_fee`	INTEGER	NOT NULL	DEFAULT 0,
	`delivery_date`	DATE	NOT NULL,
	`sale_end_at`	TIMESTAMPTZ	NOT NULL,
	`total_quantity`	INTEGER	NOT NULL,
	`min_participant_count`	INTEGER	NOT NULL,
	`min_quantity`	INTEGER	NOT NULL,
	`max_quantity_per_member`	INTEGER	NULL,
	`description`	TEXT	NULL,
	`return_policy`	TEXT	NOT NULL,
	`status`	VARCHAR(20)	NOT NULL	DEFAULT 'BIDDING',
	`awarded_at`	TIMESTAMPTZ	NULL,
	`closed_at`	TIMESTAMPTZ	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `notification_event` (
	`id`	BIGINT	NOT NULL,
	`type`	VARCHAR(40)	NOT NULL,
	`title`	VARCHAR(100)	NOT NULL,
	`body`	VARCHAR(500)	NOT NULL,
	`link_url`	VARCHAR(255)	NULL,
	`is_mandatory`	BOOLEAN	NOT NULL	DEFAULT FALSE,
	`event_key`	VARCHAR(100)	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `Payments` (
	`id`	BIGINT	NOT NULL,
	`order_id`	BIGINT	NOT NULL,
	`payment_key`	VARCHAR(200)	NULL	DEFAULT NULL	COMMENT '200자 이하',
	`order_no`	VARCHAR(64)	NULL	DEFAULT NULL	COMMENT '영문 대소문자, 숫자, 특수문자 -, _로 이루어진 6자 이상 64자 이하의 문자열',
	`order_name`	VARCHAR(255)	NULL	DEFAULT NULL	COMMENT '구매 상품',
	`total_amount`	INT	NULL	DEFAULT NULL,
	`payments_status`	VARCHAR(30)	NOT NULL	DEFAULT READY	COMMENT 'READY(결제준비), 
IN_PROGRESS,
 DONE, 
CANCELED(결제취소)',
	`payments_type`	VARCHAR(30)	NULL	COMMENT 'NORMAL(일반결제), BILLING(자동결제), BRANDPAY(브랜드페이)',
	`method`	VARCHAR(30)	NULL	COMMENT '카드, 가상계좌, 간편결제, 휴대폰, 계좌이체, 문화상품권, 도서문화상품권, 게임문화상품권',
	`approvedAt`	TIMESTAMP	NULL,
	`detail`	JSONB	NULL	COMMENT '세부데이터를 통으로 저장',
	`created_at`	TIMESTAMP	NOT NULL,
	`updated_at`	TIMESTAMP	NULL	DEFAULT NULL,
	`canceled_at`	TIMESTAMP	NULL,
	`cancel_reason`	VARCHAR(255)	NULL,
	`Key`	VARCHAR(255)	NOT NULL,
	`Key2`	VARCHAR(255)	NOT NULL
);

CREATE TABLE `GroupBuyLikes` (
	`groupbuy_id`	BIGINT	NOT NULL,
	`member_id`	BIGINT	NOT NULL
);

CREATE TABLE `category` (
	`id`	BIGINT	NOT NULL,
	`parent_id`	BIGINT	NULL,
	`name`	VARCHAR(50)	NOT NULL,
	`depth`	SMALLINT	NOT NULL,
	`facet`	TEXT	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `GroupBuy` (
	`id`	BIGINT	NOT NULL,
	`title`	VARCHAR(255)	NOT NULL,
	`target_count`	INT	NULL,
	`count`	INT	NULL,
	`group_buy_end_at`	TIMESTAMP	NULL,
	`status`	VARCHAR(30)	NULL	COMMENT '공동구매 진행중,
인원 모집 완료(결제 대기),
전 인원 결제 완료,
공동구매 종료,
공동구매 실패,
공동구매 취소',
	`seller_id`	BIGINT	NOT NULL,
	`product_id`	BIGINT	NOT NULL
);

CREATE TABLE `member` (
	`id`	BIGINT	NOT NULL,
	`login_id`	VARCHAR(20)	NULL,
	`nickname`	VARCHAR(20)	NOT NULL,
	`image`	VARCHAR(2048)	NULL,
	`phone_number`	TEXT	NULL,
	`email`	VARCHAR(255)	NULL,
	`is_seller`	BOOLEAN	NOT NULL	DEFAULT FALSE,
	`last_login_at`	TIMESTAMPTZ	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`deleted_at`	TIMESTAMPTZ	NULL,
	`Field`	TIMESTAMPTZ	NULL
);

CREATE TABLE `shipping_address` (
	`id`	BIGINT	NOT NULL,
	`member_id`	BIGINT	NOT NULL,
	`is_default`	BOOLEAN	NULL,
	`alias`	VARCHAR(30)	NOT NULL,
	`recipient_name`	VARCHAR(50)	NOT NULL,
	`phone_number`	TEXT	NOT NULL,
	`zipcode`	VARCHAR(5)	NOT NULL,
	`address`	VARCHAR(255)	NOT NULL,
	`address_detail`	VARCHAR(100)	NULL,
	`entrance_code`	VARCHAR(20)	NULL,
	`request_message`	VARCHAR(100)	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `seller` (
	`id`	BIGINT	NOT NULL,
	`member_id`	BIGINT	NOT NULL,
	`business_name`	VARCHAR(50)	NOT NULL,
	`business_number`	TEXT	NOT NULL,
	`business_number_hash`	CHAR(64)	NOT NULL,
	`mail_order_registration_number`	VARCHAR(30)	NOT NULL,
	`owner_name`	VARCHAR(50)	NOT NULL,
	`phone_number`	VARCHAR(20)	NOT NULL,
	`seller_status`	VARCHAR(20)	NOT NULL	DEFAULT 'PENDING',
	`approved_at`	TIMESTAMPTZ	NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`deleted_at`	TIMESTAMPTZ	NULL
);

CREATE TABLE `Payout` (
	`id`	BIGINT	NOT NULL,
	`seller_id`	BIGINT	NOT NULL,
	`ref_payout_id`	VARCHAR(255)	NULL	COMMENT '최대 50자',
	`pg_seller_key`	VARCHAR(35)	NULL,
	`payout_date`	VARCHAR(20)	NULL,
	`amount`	INT	NULL,
	`request_at`	TIMESTAMP	NULL,
	`status`	VARCHAR(30)	NULL	COMMENT 'REQUESTED: 지급이 요청되었지만 아직 처리되지 않은 상태입니다. REQUESTED 상태일 때만 지급대행 요청을 취소할 수 있습니다.

- IN_PROGRESS: 지급을 처리하고 있는 상태입니다.

- COMPLETED: 셀러에 지급이 완료된 상태입니다.

- FAILED: 지급 요청이 실패한 상태입니다.

- CANCELED: 지급 요청이 취소된 상태입니다.

- REJECTED: 지급 요청이 반려된 상태입니다. 웹훅은 FAILED 상태로 발송됩니다.'
);

CREATE TABLE `member_social` (
	`id`	BIGINT	NOT NULL,
	`member_id`	BIGINT	NOT NULL,
	`provider`	VARCHAR(20)	NOT NULL,
	`provider_id`	VARCHAR(255)	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `member_local` (
	`id`	BIGINT	NOT NULL,
	`member_id`	BIGINT	NOT NULL,
	`password`	VARCHAR(255)	NOT NULL,
	`password_updated_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now(),
	`created_at`	TIMESTAMPTZ	NOT NULL	DEFAULT now()
);

CREATE TABLE `reject_history` (
	`demand_id`	BIGINT	NOT NULL,
	`demand_board_id`	BIGINT	NOT NULL,
	`created_at`	TIMESTAMPTZ	NOT NULL
);

ALTER TABLE `BrandpayPayMethod` ADD CONSTRAINT `PK_BRANDPAYPAYMETHOD` PRIMARY KEY (
	`id`
);

ALTER TABLE `SellerKey` ADD CONSTRAINT `PK_SELLERKEY` PRIMARY KEY (
	`seller_id`
);

ALTER TABLE `notification_opt_out` ADD CONSTRAINT `PK_NOTIFICATION_OPT_OUT` PRIMARY KEY (
	`type`,
	`member_id`
);

ALTER TABLE `product_catalog` ADD CONSTRAINT `PK_PRODUCT_CATALOG` PRIMARY KEY (
	`id`
);

ALTER TABLE `SellerPayoutAccount` ADD CONSTRAINT `PK_SELLERPAYOUTACCOUNT` PRIMARY KEY (
	`id`
);

ALTER TABLE `demand_board` ADD CONSTRAINT `PK_DEMAND_BOARD` PRIMARY KEY (
	`id`
);

ALTER TABLE `PaymentsWebhock` ADD CONSTRAINT `PK_PAYMENTSWEBHOCK` PRIMARY KEY (
	`id`
);

ALTER TABLE `product_award_evaluation` ADD CONSTRAINT `PK_PRODUCT_AWARD_EVALUATION` PRIMARY KEY (
	`id`
);

ALTER TABLE `BrandPayToken` ADD CONSTRAINT `PK_BRANDPAYTOKEN` PRIMARY KEY (
	`member_id`
);

ALTER TABLE `CustomerKey` ADD CONSTRAINT `PK_CUSTOMERKEY` PRIMARY KEY (
	`member_id`
);

ALTER TABLE `notification` ADD CONSTRAINT `PK_NOTIFICATION` PRIMARY KEY (
	`id`
);

ALTER TABLE `demand` ADD CONSTRAINT `PK_DEMAND` PRIMARY KEY (
	`id`
);

ALTER TABLE `Orders` ADD CONSTRAINT `PK_ORDERS` PRIMARY KEY (
	`id`
);

ALTER TABLE `outbox_event` ADD CONSTRAINT `PK_OUTBOX_EVENT` PRIMARY KEY (
	`id`
);

ALTER TABLE `product` ADD CONSTRAINT `PK_PRODUCT` PRIMARY KEY (
	`id`
);

ALTER TABLE `notification_event` ADD CONSTRAINT `PK_NOTIFICATION_EVENT` PRIMARY KEY (
	`id`
);

ALTER TABLE `Payments` ADD CONSTRAINT `PK_PAYMENTS` PRIMARY KEY (
	`id`
);

ALTER TABLE `category` ADD CONSTRAINT `PK_CATEGORY` PRIMARY KEY (
	`id`
);

ALTER TABLE `GroupBuy` ADD CONSTRAINT `PK_GROUPBUY` PRIMARY KEY (
	`id`
);

ALTER TABLE `member` ADD CONSTRAINT `PK_MEMBER` PRIMARY KEY (
	`id`
);

ALTER TABLE `shipping_address` ADD CONSTRAINT `PK_SHIPPING_ADDRESS` PRIMARY KEY (
	`id`
);

ALTER TABLE `seller` ADD CONSTRAINT `PK_SELLER` PRIMARY KEY (
	`id`
);

ALTER TABLE `Payout` ADD CONSTRAINT `PK_PAYOUT` PRIMARY KEY (
	`id`
);

ALTER TABLE `member_social` ADD CONSTRAINT `PK_MEMBER_SOCIAL` PRIMARY KEY (
	`id`
);

ALTER TABLE `member_local` ADD CONSTRAINT `PK_MEMBER_LOCAL` PRIMARY KEY (
	`id`
);

ALTER TABLE `reject_history` ADD CONSTRAINT `PK_REJECT_HISTORY` PRIMARY KEY (
	`demand_id`,
	`demand_board_id`
);

ALTER TABLE `SellerKey` ADD CONSTRAINT `FK_seller_TO_SellerKey_1` FOREIGN KEY (
	`seller_id`
)
REFERENCES `seller` (
	`id`
);

ALTER TABLE `notification_opt_out` ADD CONSTRAINT `FK_member_TO_notification_opt_out_1` FOREIGN KEY (
	`member_id`
)
REFERENCES `member` (
	`id`
);

ALTER TABLE `BrandPayToken` ADD CONSTRAINT `FK_member_TO_BrandPayToken_1` FOREIGN KEY (
	`member_id`
)
REFERENCES `member` (
	`id`
);

ALTER TABLE `CustomerKey` ADD CONSTRAINT `FK_member_TO_CustomerKey_1` FOREIGN KEY (
	`member_id`
)
REFERENCES `member` (
	`id`
);

ALTER TABLE `reject_history` ADD CONSTRAINT `FK_demand_TO_reject_history_1` FOREIGN KEY (
	`demand_id`
)
REFERENCES `demand` (
	`id`
);

ALTER TABLE `reject_history` ADD CONSTRAINT `FK_demand_board_TO_reject_history_1` FOREIGN KEY (
	`demand_board_id`
)
REFERENCES `demand_board` (
	`id`
);

