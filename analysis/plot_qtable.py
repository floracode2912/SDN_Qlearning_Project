import json
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
import os

QTABLE_PATH = "/home/npt/SDN_Qlearning_Project/analysis/qtable_case3.json"

def visualize_qtable(path):
    if not os.path.exists(path):
        print("[ERROR] Không tìm thấy file Q-table!")
        return

    with open(path, "r") as f:
        q_data = json.load(f)

    # Chuyển Q-table sang dạng DataFrame
    rows = []
    for state, actions in q_data.items():
        state_str = f"{state[0]} → {state[1]}"
        for act, q_val in actions.items():
            rows.append({"State": state_str, "Action": act, "Q-value": q_val})

    df = pd.DataFrame(rows)

    if df.empty:
        print("[INFO] Q-table hiện đang trống (controller chưa học đủ).")
        return

    pivot_df = df.pivot(index="State", columns="Action", values="Q-value")

    plt.figure(figsize=(10, 6))
    sns.heatmap(pivot_df, annot=True, cmap="viridis", fmt=".2f", cbar_kws={'label': 'Q-value'})
    plt.title("📈 Q-learning Heatmap (Case 3)")
    plt.xlabel("Action (output port)")
    plt.ylabel("State (src → dst)")
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    visualize_qtable(QTABLE_PATH)
