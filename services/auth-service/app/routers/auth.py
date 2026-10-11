import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import user_service
from app.database import get_db
from app.deps import active_admin, active_user
from app.metrics import LOGINS
from app.models import User
from app.passwords import verify_password
from app.ratelimit import login_rate_limit
from app.schemas import LoginRequest, PasswordChange, TokenResponse, UserCreate, UserOut
from app.tokens import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("app.auth")


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_rate_limit)])
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = user_service.authenticate(db, body.username, body.password)
    if user is None:
        LOGINS.labels(result="failure").inc()
        logger.warning("login failed", extra={"event": "login_failed"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = create_access_token(user)
    LOGINS.labels(result="success").inc()
    logger.info(f"login ok user_id={user.id}", extra={"event": "login_ok"})
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, _admin: User = Depends(active_admin), db: Session = Depends(get_db)):
    return user_service.create_user(db, body)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(active_user)):
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange, user: User = Depends(active_user), db: Session = Depends(get_db)
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user_service.set_password(db, user, body.new_password)
