import json
import os
import threading
from datetime import datetime
import discord
from discord import app_commands, ui
from discord.ext import commands
from flask import Flask

# --- Render 포트 바인딩용 가짜 웹 서버 ---
app = Flask('')


@app.route('/')
def home():
  return 'Bot is alive!'


def run():
  app.run(host='0.0.0.0', port=8080)


def keep_alive():
  t = threading.Thread(target=run, daemon=True)
  t.start()


keep_alive()  # 웹 서버 미리 실행

# --- 디스코드 봇 설정 ---
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

DATA_FILE = 'reservations.json'
# (이 아래부터 기존의 load_reservations() 코드 그대로 유지)
# --- 데이터 저장 및 로드 함수 ---
def load_reservations():
  if os.path.exists(DATA_FILE):
    try:
      with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)
    except Exception:
      return []
  return []


def save_reservations(data):
  with open(DATA_FILE, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=4)


# ★ 함수 선언이 모두 끝난 후 실행!
reservations = load_reservations()

# 시간 중복 체크 함수 (서버별 구분)
def check_overlap(guild_id, room, date, start_str, end_str):
    try:
        new_start = datetime.strptime(f"{date} {start_str}", "%Y-%m-%d %H:%M")
        new_end = datetime.strptime(f"{date} {end_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return True, "⚠️ 날짜나 시간 형식이 올바르지 않습니다. (예: 2026-07-31 / 15:00)"

    if new_start >= new_end:
        return True, "⚠️ 종료 시간은 시작 시간보다 이후여야 합니다."

    for r in reservations:
        if r.get("guild_id") == guild_id and r["room"] == room and r["date"] == date:
            existing_start = datetime.strptime(f"{r['date']} {r['start']}", "%Y-%m-%d %H:%M")
            existing_end = datetime.strptime(f"{r['date']} {r['end']}", "%Y-%m-%d %H:%M")

            if new_start < existing_end and new_end > existing_start:
                return True, f"⚠️ **{room}**은(는) 해당 시간대({r['start']}~{r['end']})에 이미 예약이 존재합니다!"

    return False, ""

# --- 회의실 예약 모달 (입력 폼) ---
class RoomReservationModal(ui.Modal, title='회의실 예약'):
    room = ui.TextInput(label='회의실', placeholder='예: 회의실 A', default='회의실 A', required=True)
    date = ui.TextInput(label='날짜', placeholder='YYYY-MM-DD (예: 2026-07-31)', default='2026-07-31', required=True)
    start_time = ui.TextInput(label='시작 시간', placeholder='HH:MM (예: 15:00)', default='15:00', required=True)
    end_time = ui.TextInput(label='종료 시간', placeholder='HH:MM (예: 16:00)', default='16:00', required=True)
    purpose = ui.TextInput(label='사용 목적', placeholder='예: 주간 기획 회의', style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id

        # 1. 중복 검사
        is_overlapped, err_msg = check_overlap(
            guild_id, self.room.value, self.date.value, self.start_time.value, self.end_time.value
        )

        if is_overlapped:
            await interaction.response.send_message(err_msg, ephemeral=True)
            return

        # 2. 고유 예약 데이터 생성
        res_id = f"{guild_id}_{self.room.value}_{self.date.value}_{self.start_time.value}"
        res_data = {
            "id": res_id,
            "guild_id": guild_id,
            "room": self.room.value,
            "date": self.date.value,
            "start": self.start_time.value,
            "end": self.end_time.value,
            "user_id": interaction.user.id,
            "user_name": interaction.user.display_name,
            "purpose": self.purpose.value
        }
        reservations.append(res_data)
        save_reservations(reservations)

        # 3. 예약 카드 생성
        embed = discord.Embed(title="✅ 회의실 예약 완료", color=discord.Color.green())
        embed.add_field(name="회의실", value=self.room.value, inline=False)
        embed.add_field(name="일시", value=f"{self.date.value} {self.start_time.value}~{self.end_time.value}", inline=False)
        embed.add_field(name="예약자", value=interaction.user.mention, inline=True)
        embed.add_field(name="목적", value=self.purpose.value, inline=True)

        # 4. 버튼 추가
        view = ui.View()
        btn_edit = ui.Button(label="예약 변경", style=discord.ButtonStyle.secondary, custom_id=f"edit_{res_id}")
        btn_cancel = ui.Button(label="예약 취소", style=discord.ButtonStyle.danger, custom_id=f"cancel_{res_id}")
        btn_status = ui.Button(label="예약 현황", style=discord.ButtonStyle.primary, custom_id="status_btn")

        view.add_item(btn_edit)
        view.add_item(btn_cancel)
        view.add_item(btn_status)

        await interaction.response.send_message(embed=embed, view=view)

# --- 봇 이벤트 및 명령어 ---
@client.event
async def on_ready():
    print(f'✅ {client.user} (으)로 로그인되었습니다!')
    try:
        synced = await tree.sync()
        print(f"✅ {len(synced)}개의 슬래시 명령어가 동기화되었습니다.")
    except Exception as e:
        print(f"동기화 중 오류 발생: {e}")

@tree.command(name="회의실예약", description="회의실 예약을 위한 입력 창을 엽니다.")
async def reserve_room(interaction: discord.Interaction):
    await interaction.response.send_modal(RoomReservationModal())

@tree.command(name="회의실현황", description="현재 서버의 회의실 예약 현황을 조회합니다.")
async def show_status(interaction: discord.Interaction):
    await send_status_embed(interaction)

async def send_status_embed(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    server_res = [r for r in reservations if r.get("guild_id") == guild_id]

    if not server_res:
        await interaction.response.send_message("📅 현재 등록된 회의실 예약이 없습니다.", ephemeral=True)
        return

    embed = discord.Embed(title="📅 회의실 예약 현황", color=discord.Color.blue())
    for idx, r in enumerate(server_res, 1):
        embed.add_field(
            name=f"{idx}. {r['room']} ({r['date']})",
            value=f"• **시간**: {r['start']}~{r['end']}\n• **예약자**: {r['user_name']}\n• **목적**: {r['purpose']}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# 버튼 인터랙션 처리 (공개 취소 메시지 적용)
@client.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id", "")

        if custom_id == "status_btn":
            await send_status_embed(interaction)

        elif custom_id.startswith("cancel_"):
            res_id = custom_id.replace("cancel_", "")
            target = next((r for r in reservations if r["id"] == res_id), None)

            if not target:
                await interaction.response.send_message("⚠️ 이미 취소되었거나 존재하지 않는 예약입니다.", ephemeral=True)
                return

            # 예약자 본인 또는 서버 관리자 권한 확인
            is_owner = (target["user_id"] == interaction.user.id)
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_owner or is_admin):
                # 권한 오류 메시지는 나에게만 보임
                await interaction.response.send_message("❌ 본인의 예약만 취소할 수 있습니다!", ephemeral=True)
                return

            reservations.remove(target)
            save_reservations(reservations)
            
            # 📢 취소 안내 카드 (모든 사용자가 채널에서 볼 수 있음!)
            cancel_embed = discord.Embed(
                title="🗑️ 회의실 예약 취소",
                description=f"{interaction.user.mention} 님이 예약을 취소했습니다.",
                color=discord.Color.red()
            )
            cancel_embed.add_field(name="회의실", value=target['room'], inline=True)
            cancel_embed.add_field(name="일시", value=f"{target['date']} {target['start']}~{target['end']}", inline=True)
            
            # ephemeral 옵션을 제외하여 공개 메시지로 전송
            await interaction.response.send_message(embed=cancel_embed)

        elif custom_id.startswith("edit_"):
            res_id = custom_id.replace("edit_", "")
            target = next((r for r in reservations if r["id"] == res_id), None)

            if not target:
                await interaction.response.send_message("⚠️ 이미 취소되었거나 존재하지 않는 예약입니다.", ephemeral=True)
                return

            is_owner = (target["user_id"] == interaction.user.id)
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_owner or is_admin):
                await interaction.response.send_message("❌ 본인의 예약만 변경할 수 있습니다!", ephemeral=True)
                return

            # 기존 예약 삭제 후 새 모달 오픈
            reservations.remove(target)
            save_reservations(reservations)
            await interaction.response.send_modal(RoomReservationModal())
import os

# Render 서버에 등록할 DISCORD_TOKEN 환경변수를 우선 읽어오고, 없으면 기존 토큰 사용
TOKEN = os.environ.get("DISCORD_TOKEN")

client.run(TOKEN)
