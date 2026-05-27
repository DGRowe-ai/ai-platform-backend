from fastapi import HTTPException, Depends
from auth_utils import get_current_user

# ============================
# REQUIRE A SINGLE ROLE
# ============================
def require_role(required_role: str):
    def role_checker(user = Depends(get_current_user)):
        if user.role != required_role:
            raise HTTPException(status_code=403, detail="Access denied")
        return user
    return role_checker


# ============================
# REQUIRE MULTIPLE ROLES
# (admin OR owner, etc.)
# ============================
def require_roles(roles: list):
    def checker(user = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Access denied")
        return user
    return checker
