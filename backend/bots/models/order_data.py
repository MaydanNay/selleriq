from datetime import datetime, timezone
from pydantic import BaseModel, field_validator, Field
from typing import Optional

class OrderData(BaseModel):
    agent_id: str
    bouquet_id: str
    bouquet_title: str
    bouquet_type: str
    bouquet_quantity: int
    bouquet_price: float
    variant_bouquet_title: str
    variant_bouquet_data: str
    additional_product_name: Optional[str] = Field(default="")
    additional_product_quantity: Optional[int] = Field(default=0)
    additional_product_price: Optional[float] = Field(default=0.0)
    description_order: Optional[str] = Field(default="")
    delivery: bool
    delivery_address: Optional[str] = Field(default="")
    delivery_street: Optional[str] = Field(default="")
    delivery_house: Optional[str] = Field(default="")
    delivery_building: Optional[str] = Field(default="")
    delivery_apartment: Optional[str] = Field(default="")
    delivery_comments: Optional[str] = Field(default="")
    delivery_contact: Optional[str] = Field(default="")
    delivery_phone: Optional[str] = Field(default="")
    delivery_datetime: Optional[str] = Field(default="")
    total_cost: float
    customer_name: str
    customer_phone: str
    customer_gender: str
    customer_instagram: Optional[str] = Field(default="")

    # Проверка обязательных текстовых полей на пустоту с конкретными сообщениями
    @field_validator("bouquet_id")
    def check_bouquet_id_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Поле 'bouquet_id' не может быть пустым")
        return v

    @field_validator("bouquet_title")
    def check_bouquet_title_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Поле 'bouquet_title' не может быть пустым")
        return v

    @field_validator("customer_name")
    def check_customer_name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Поле 'customer_name' не может быть пустым")
        return v

    @field_validator("customer_phone")
    def check_customer_phone_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Поле 'customer_phone' не может быть пустым")
        return v

    @field_validator("customer_gender")
    def check_customer_gender_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Поле 'customer_gender' не может быть пустым")
        return v

    # Проверка количества букетов
    @field_validator("bouquet_quantity")
    def check_positive_quantity(cls, v):
        if v <= 0:
            raise ValueError("Количество букета должно быть больше нуля")
        return v

    # Проверка стоимости букета
    @field_validator("bouquet_price")
    def check_non_negative_price(cls, v):
        if v < 0:
            raise ValueError("Стоимость букета не может быть отрицательной")
        return v

    # Валидатор для additional_product_quantity
    @field_validator("additional_product_quantity")
    def check_additional_quantity(cls, v, info):
        additional_product_name = info.data.get("additional_product_name", "")
        if additional_product_name.strip() and v <= 0:
            raise ValueError("Количество дополнительного продукта должно быть больше нуля")
        return v

    # Валидатор для additional_product_price
    @field_validator("additional_product_price")
    def check_additional_price(cls, v, info):
        additional_product_name = info.data.get("additional_product_name", "")
        if additional_product_name.strip() and v < 0:
            raise ValueError("Стоимость дополнительного продукта не может быть отрицательной")
        return v

    # Валидатор для delivery_address
    @field_validator("delivery_address")
    def check_delivery_address(cls, v, info):
        delivery = info.data.get("delivery")
        if delivery and not v.strip():
            raise ValueError("Адрес доставки не должен быть пустым при включенной доставке")
        return v

    # Валидатор для delivery_datetime
    @field_validator("delivery_datetime")
    def validate_delivery_datetime(cls, v: str) -> str:
        # Если поле пустое - ничего не проверяем
        if not v or not v.strip():
            return v

        # Попытка распарсить строку в datetime
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("""
                Неверный формат даты и времени доставки.
                Используйте ISO-формат, например: 2025-06-01T14:30
            """)

        # Проверка, что дата/время в будущем
        if dt <= datetime.now():
            raise ValueError("Время доставки должно быть в будущем")

        return v