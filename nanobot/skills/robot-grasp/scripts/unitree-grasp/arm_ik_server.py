import numpy as np
import pinocchio as pin
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List

from control.g1_arm_ik import G1_29_ArmIK

arm_ik_solver = G1_29_ArmIK()

class IKRequest(BaseModel):
    left_pos: List[float]
    right_pos: List[float]

class IKResponse(BaseModel):
    success: bool
    joints: List[float]

app = FastAPI()

@app.post("/api/server/ik")
def ik_server(request: IKRequest) -> IKResponse:
    left_pos = request.left_pos
    right_pos = request.right_pos

    L_tf_target = pin.SE3(
        pin.utils.rpyToMatrix(np.array(left_pos[3:])),
        np.array(left_pos[:3]),
    )
    R_tf_target = pin.SE3(
        pin.utils.rpyToMatrix(np.array(right_pos[3:])),
        np.array(right_pos[:3]),
    )

    try:
        sol_q, sol_tauff = arm_ik_solver.solve_ik(L_tf_target.homogeneous, R_tf_target.homogeneous)

        q = sol_q.tolist()[0:14] + [0]*3
        return IKResponse(success=True, joints=q)

    except Exception as e:
        print(f"IK solver error: {e}")
        return IKResponse(success=False, joints=[])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=50021)
