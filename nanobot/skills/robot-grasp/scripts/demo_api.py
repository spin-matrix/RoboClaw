import time
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from action_executor import ActionExecutor
from yolo_detector import YOLODetector


executor = ActionExecutor()
detector = YOLODetector("./models/yolov8s-seg.pt", False)
detector.start()

# ---------------- FastAPI App ----------------
app = FastAPI()

@app.get("/api/unitree/grasp")
def unitree_grasp(target: str=None):
    try:
        if target is None:
            return JSONResponse(status_code=500, content={"error": "No target provided."})

        # Step 1: Detect objects
        while True:
            detection = detector.get_interested_detection(target)
            if detection:
                coords = detection["world"]
                if coords[0] > 1.0:
                    print(f"Detected object is too far for grasp.")
                    continue
                else:
                    break
            time.sleep(1)
        # coords = [0.36, -0.1, 0.1]

        # input("Check and Press any key to continue.")

        # Step 2: Move to expected distance
        cur_dis = coords[0]
        expect_dis = 0.4
        if cur_dis > expect_dis:
            executor.move_forward(cur_dis-expect_dis+0.1)
        else:
            print("Already within expected distance.")

        # Step 3: Execute grasping action
        while True:
            detection = detector.get_interested_detection(target)
            if detection:
                coords = detection["world"]
                if coords[0] > 1.0:
                    print(f"Detected object is too far for grasp.")
                    continue
                else:
                    break
            time.sleep(1)
        # coords = [0.36, -0.1, 0.1]

        # input("Check and Press any key to continue.")
        suc = executor.grasp(coords)

        if suc:
            return JSONResponse(status_code=200, content={"message": "Grasp success."})
        else:
            print("Grasping failed.")
            return JSONResponse(status_code=500, content={"error": "Grasp failed."})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/unitree/regrasp")
def unitree_regrasp(target: str=None):
    try:
        if target is None:
            return JSONResponse(status_code=500, content={"error": "No target provided."})

        # Step 1: Detect objects
        while True:
            detection = detector.get_interested_detection(target)
            if detection:
                coords = detection["world"]
                if coords[0] > 1.0:
                    print(f"Detected object is too far for grasp.")
                    continue
                else:
                    break
            time.sleep(1)
        # coords = [0.36, -0.1, 0.1]

        # input("Check and Press any key to continue.")
    
        suc = executor.regrasp(coords)
        if suc:
            return JSONResponse(status_code=200, content={"message": "Regrasp success."})
        else:
            print("Regrasp failed.")
            return JSONResponse(status_code=500, content={"error": "Regrasp failed."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/unitree/retract")
def unitree_retract():
    try:
        suc = executor.retract()
        if suc:
            return JSONResponse(status_code=200, content={"message": "Retract success."})
        else:
            print("Retract failed.")
            return JSONResponse(status_code=500, content={"error": "Retract failed."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/unitree/handover")
def unitree_handover():
    try:
        # Step 1: Detect person
        while True:
            detection = detector.get_interested_detection("person")
            if detection:
                coords = detection["world"]
                if coords[0] > 3.0:
                    print(f"Detected huamn is too far for handover.")
                    continue
                else:
                    break
            time.sleep(1)

        # Step 2: Move to expected distance
        cur_dis = coords[0]
        expect_dis = 0.6
        if cur_dis > expect_dis:
            executor.move_forward(cur_dis-expect_dis)
        else:
            print("Already within expected distance.")

        # Step 3: Execute handover action
        suc = executor.hand_over()
        if suc:
            return JSONResponse(status_code=200, content={"message": "Handover success."})
        else:
            print("Handover failed.")
            return JSONResponse(status_code=500, content={"error": "Handover failed."})
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/unitree/stop")
def unitree_stop():
    try:
        executor.is_running = False
        executor.release()
        return JSONResponse(status_code=200, content={"message": "Stop success."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/unitree/stop_move")
def unitree_stop_move():
    try:
        executor.stop_move()
        return JSONResponse(status_code=200, content={"message": "Stop move success."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})  


if __name__ == "__main__":
    try:
        uvicorn.run(app, host="0.0.0.0", port=8080)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        executor.is_running = False
        executor.release() 
        detector.stop()