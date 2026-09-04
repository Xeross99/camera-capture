// ext_servo.h — dodatkowe serwo magistrali (ST3215) POZA pięcioma fabrycznymi
// serwami RoArm-M2-S. W Camera Capture to piąta oś: pochylenie kamery
// (tilt) zamontowane na końcu wysięgnika za osią 4.
//
// Fabryczny firmware zna tylko ID 11–15 i trzyma ich feedback w tablicy
// `servoFeedback[5]` indeksowanej `id - 11` — każde inne ID trafiałoby POZA
// tablicę (`changeID` z komendą 501 robi dokładnie to dla nowego serwa z
// fabrycznym ID 1). Dlatego wszystkie funkcje tutaj gadają z serwem
// bezpośrednio przez `st` (SCServo) i nie dotykają tamtej tablicy.
//
// Jednostki są CELOWO surowe (kroki serwa), bez przeliczeń przez stopnie/s
// jak w komendach 121/122: klient (src/robot.py) wysyła `spd`/`acc` dokładnie
// tak, jak trzyma je w konfiguracji (ROBOT_JOINT_SPEED 1..4096,
// ROBOT_JOINT_ACC 1..254), więc ta sama liczba znaczy to samo po obu stronach.
// Kąt: 0° = środek zakresu serwa (krok 2047, jak ARM_SERVO_MIDDLE_POS), zakres
// −180…+180°, jeden pełny obrót = 4096 kroków.
//
// Komendy (numery w json_cmd.h):
//   {"T":130,"id":16,"angle":30.0,"spd":1200,"acc":40}   ruch na kąt
//   {"T":131,"id":16}                                    odczyt →
//       {"T":1131,"id":16,"ok":1,"angle":30.1,"pos":2389,"load":12,"volt":12.1,"temp":31}
//       {"T":1131,"id":16,"ok":0}                        gdy serwo nie odpowiada
//   {"T":132,"id":16,"cmd":0|1}                          moment OFF/ON
//   {"T":134,"raw":1,"new":16}                           zmiana ID (bezpieczna
//       dla KAŻDEGO raw, w odróżnieniu od 501) →
//       {"T":1134,"raw":1,"new":16,"ok":1}
//
// Odpowiedzi idą po Serial tak samo jak feedback 1051 (`Serial.println` =
// zakończenie "\r\n"), więc klient rozpoznaje je po polu "T".

#define EXT_SERVO_MIDDLE_POS 2047
#define EXT_SERVO_POS_RANGE  4096

int extServoPosByAngle(double angle) {
  int pos = EXT_SERVO_MIDDLE_POS + (int)round(angle / 360.0 * EXT_SERVO_POS_RANGE);
  return constrain(pos, 0, EXT_SERVO_POS_RANGE - 1);
}

double extServoAngleByPos(int pos) {
  return (pos - EXT_SERVO_MIDDLE_POS) * 360.0 / EXT_SERVO_POS_RANGE;
}

// {"T":130,...}: ruch na kąt. spd w krokach/s (0 = maks.), acc w krokach (0 =
// bez rampy) — surowe argumenty `WritePosEx`.
void extServoAngleCtrl(byte id, double angle, u16 spd, u8 acc) {
  int pos = extServoPosByAngle(angle);
  st.WritePosEx(id, pos, spd, acc);
  if (InfoPrint == 1) {
    Serial.print("ext servo "); Serial.print(id);
    Serial.print(" -> "); Serial.print(angle); Serial.print(" deg = pos ");
    Serial.println(pos);
  }
}

// {"T":131,...}: odczyt. `ok:0` gdy serwo nie odpowiada (brak zasilania,
// złe ID, niepodpięty kabel) — klient odróżnia to od zerwanego łącza z płytką.
void extServoFeedback(byte id) {
  jsonInfoHttp.clear();
  jsonInfoHttp["T"] = 1131;
  jsonInfoHttp["id"] = id;
  if (st.FeedBack(id) != -1) {
    int pos = st.ReadPos(-1);
    jsonInfoHttp["ok"] = 1;
    jsonInfoHttp["pos"] = pos;
    jsonInfoHttp["angle"] = extServoAngleByPos(pos);
    jsonInfoHttp["load"] = st.ReadLoad(-1);
    jsonInfoHttp["volt"] = st.ReadVoltage(-1) / 10.0;
    jsonInfoHttp["temp"] = st.ReadTemper(-1);
  } else {
    jsonInfoHttp["ok"] = 0;
  }
  String out;
  serializeJson(jsonInfoHttp, out);
  Serial.println(out);
}

// {"T":132,...}: moment jednego serwa. Komenda 210 (broadcast 254) i tak
// obejmuje wszystkie serwa na magistrali, łącznie z tym — ta jest do
// pojedynczego sterowania, np. przy ustawianiu samego pochylenia ręką.
void extServoTorque(byte id, u8 cmd) {
  st.EnableTorque(id, cmd);
}

// {"T":134,...}: zmiana ID bez przechodzenia przez `servoFeedback[raw - 11]`.
// Nowe ST3215 ma fabrycznie ID 1; na magistrali ramienia wolne są ID > 15.
void extServoChangeId(byte rawId, byte newId) {
  jsonInfoHttp.clear();
  jsonInfoHttp["T"] = 1134;
  jsonInfoHttp["raw"] = rawId;
  jsonInfoHttp["new"] = newId;
  bool ok = false;
  if (st.FeedBack(rawId) != -1) {
    st.unLockEprom(rawId);
    st.writeByte(rawId, SMS_STS_ID, newId);
    st.LockEprom(newId);
    ok = st.FeedBack(newId) != -1;
  }
  jsonInfoHttp["ok"] = ok ? 1 : 0;
  String out;
  serializeJson(jsonInfoHttp, out);
  Serial.println(out);
}
