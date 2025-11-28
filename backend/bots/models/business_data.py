# # business_data.py
# from typing import List, Optional
# from pydantic import BaseModel, Field
# from sqlalchemy import Column, Integer, String, Table, ForeignKey, Text
# from sqlalchemy.orm import relationship, declarative_base
# from sqlalchemy.dialects.postgresql import JSON
# business_days = Column(JSON, nullable=True)

# Base = declarative_base()

# # ORM-модель для хранения в БД
# class BusinessDataORM(Base):
#     __tablename__ = 'business_data'

#     id = Column(Integer, primary_key=True, index=True)
#     business_name = Column(String(255), nullable=False)
#     business_niche = Column(String(255), nullable=False)
#     business_description = Column(Text, nullable=True)
#     business_address = Column(String(255), nullable=False)

#     # Доп. поля
#     business_hours = Column(String(100), nullable=True)
    
#     # Для списковых полей создадим простые JSON-строки или отдельные таблицы
#     business_days = Column(JSON, nullable=True)
#     business_delivery = Column(JSON, nullable=True)
#     business_payment = Column(JSON, nullable=True)
#     business_payment_type = Column(JSON, nullable=True)

#     # Контакты
#     business_phone = Column(String(100), nullable=True)
#     business_website = Column(String(255), nullable=True)
#     business_instagram = Column(String(255), nullable=True)
#     business_whatsapp = Column(String(255), nullable=True)
#     business_telegram = Column(String(255), nullable=True)

#     agent_name  = Column(String(100), nullable=True)
#     bot_style = Column(String(100), nullable=True)


# # Pydantic-схемы для валидации входящих/исходящих данных
# class BusinessDataBase(BaseModel):
#     business_name: str = Field(..., title="Название бизнеса")
#     business_niche: str = Field(..., title="Ниша")
#     business_description: Optional[str] = Field(None, title="Описание")
#     business_address: str = Field(..., title="Адрес")

# class BusinessDataStep2(BaseModel):
#     business_hours: Optional[str] = Field(None, title="Часы работы")
#     business_days: Optional[List[str]] = Field(None, title="Дни работы")
#     business_delivery: Optional[List[str]] = Field(None, title="Варианты доставки")
#     business_payment: Optional[List[str]] = Field(None, title="Варианты оплаты")
#     business_payment_type: Optional[List[str]] = Field(None, title="Тип оплаты")

# class BusinessDataStep3(BaseModel):
#     business_phone: Optional[str]
#     business_website: Optional[str]
#     business_instagram: Optional[str]
#     business_whatsapp: Optional[str]
#     business_telegram: Optional[str]

# class BusinessDataStep4(BaseModel):
#     agent_name: str
#     bot_style: str
