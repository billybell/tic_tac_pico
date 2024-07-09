import bluetooth
from ble_advertising import decode_services, decode_name
from micropython import const
import sys
import time
import uselect

_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_SERVICE_DONE = const(10)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_READ_RESULT = const(15)
_IRQ_GATTC_NOTIFY = const(18)

_ADV_IND = const(0x00)
_ADV_DIRECT_IND = const(0x01)

_GAME_UUID = bluetooth.UUID("d314caba614b43c3a05fec9a48d85750")
_GAME_STATE_UUID = bluetooth.UUID("a3d11e79-dfe4-461a-83c1-da99f708018d")

class TicTacToe:
    def __init__(self, ble):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)
        self._reset()
        
    def _reset(self):
        self._board = ['1','2','3','4','5','6','7','8','9']
        self._step = -1
        self._starts = -1
        self._p1_wins = 0
        self._p2_wins = 0
        self._draws = 0
        self._input_waiting = False
        self._addr_type = None
        self._addr = None
        
        self._scan_callback = None
        # self._conn_callback = None
        # self._read_callback = None
        
        self._name = None
        # self._notify_callback = None
        
        self._conn_handle = None
        self._start_handle = None
        self._end_handle = None
        
        self._handle_game_state = None
        
        
    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            if adv_type in (_ADV_IND, _ADV_DIRECT_IND):
                type_list = decode_services(adv_data)
                if _GAME_UUID in type_list:
                    self._addr_type = addr_type
                    self._addr = bytes(addr)
                    self._name = decode_name(adv_data) or "?"
                    self._ble.gap_scan(None)
        elif event == _IRQ_SCAN_DONE:
            if self._scan_callback:
                if self._addr:
                    self._scan_callback(self._addr_type, self._addr, self._name)
                    self._scan_callback = None
                else:
                    self._scan_callback(None, None, None)
                 
        elif event == _IRQ_PERIPHERAL_CONNECT:
            conn_handle, addr_type, addr = data
            if addr_type == self._addr_type and addr == self._addr:
                self._conn_handle = conn_handle
                self._ble.gattc_discover_services(self._conn_handle)
            
        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            conn_handle, _, _ = data
            if conn_handle == self._conn_handle:
                self._reset()
                
        elif event == _IRQ_GATTC_SERVICE_RESULT:
            conn_handle, start_handle, end_handle, uuid = data
            if conn_handle == self._conn_handle and uuid == _GAME_UUID:
                self._start_handle, self._end_handle = start_handle, end_handle
                
        elif event == _IRQ_GATTC_SERVICE_DONE:
            if self._start_handle and self._end_handle:
                self._ble.gattc_discover_characteristics(
                    self._conn_handle, self._start_handle, self._end_handle   
                )
            else:
                print("Failed to find game service!")
                
        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            conn_handle, def_handle, value_handle, properties, uuid = data
            if conn_handle == self._conn_handle:
                if uuid == _GAME_STATE_UUID:
                    self._handle_game_state = value_handle
                else:
                    print(f"Unknown characteristic {uuid}")
        
        elif event == _IRQ_GATTC_READ_RESULT:
            conn_handle, value_handle, char_data = data
            if conn_handle == self._conn_handle:
                if self._handle_game_state == value_handle:
                    instructions = list(bytes(char_data).decode("UTF-8"))
                    if len(instructions) == 3:
                        starts = int(instructions.pop(0))
                        step = int(instructions.pop(0))
                        move = int(instructions.pop(0))
                        self.advance_game_state(starts, step, move)
                    
        elif event == _IRQ_GATTC_NOTIFY:
            conn_handle, value_handle, notify_data = data
            if self._handle_game_state is not None and value_handle == self._handle_game_state:
                instructions = list(bytes(notify_data).decode("UTF-8"))
                if len(instructions) == 3:
                    starts = int(instructions.pop(0))
                    step = int(instructions.pop(0))
                    move = int(instructions.pop(0))
                    self.advance_game_state(starts, step, move)
                else:
                    print("Wrong number of instructions: " + str(len(instructions)))
                
            else:
                print("Unhandled notify!")
                print(value_handle)
        
    def advance_game_state(self, starts, step, move):
        # print(f"starts: {starts}, step: {step}, move: {move}, self._step: {self._step}")
        game_over = False
        self._starts = starts
        if self._step == -1 and step == 0:
            # new game
            if self._p2_wins + self._p1_wins + self._draws == 0:
                print("Let's play!")
            else:
                print("Let's go again!")
            if starts == 0:
                self.print_board()
                print("Host goes first this time.")
            else:
                print("We go first this time.")
        # the host will be one step ahead of us after they move
        elif self._step + 1 == step and move != 0:
            if self.is_free(move):
                self._board[move - 1] = 'X'  # host
                print("Host took square " + str(move))
                if self.is_winner(1):
                    print("Host wins!")
                    self._p1_wins += 1
                    game_over = True
                elif self.is_board_full():
                    print("It's a draw!!")
                    self._draws += 1
                    game_over = True
            else:
                print("Host tried to take square " + str(move) + " but it's not free...")
        
        if game_over:
            self.print_board()
            self.print_stats()
            self.reset_board()
        else:
            self._step = step
            self._move = move
        if self._step != -1 and (self._starts + self._step) % 2 == 1:
            if self._input_waiting == False:
                self.print_board()
                print("What's your move (O)?")
            self._input_waiting = True

    def is_free(self, move):
        if self._board[move - 1] == str(move):
            return True
        else:
            return False
        
    def write_instructions(self):
        # the only data we need to replicate between devices is:
        # - who started this game
        # - which step (turn) we are on
        # - what the last move was
        instructions = str(self._starts) + str(self._step) + str(self._move)
        self._ble.gattc_write(self._conn_handle, self._handle_game_state, instructions.encode("UTF-8"), 1)
        
    def make_move(self, move):
        if self.is_free(move):
            self._board[move - 1] = 'O'
            self._move = move
            self._step += 1
            self.write_instructions()
            if self.is_winner(2):
                print("We won!!")
                self._p2_wins += 1
                self.print_board()
                self.print_stats()
                self.reset_board()
            elif self.is_board_full():
                print("It's a draw!!")
                self._draws += 1
                self.print_board()
                self.print_stats()
                self.reset_board()
            else:
                print("We took square " + str(move) + ".")
                self.print_board()
                print("Waiting for host to move...")
                self._input_waiting = False
        else:
            print(f"Sqare {move} is not available, try again...")
            self.print_board()
    
    def print_stats(self):
        print("Stats so far:")
        print("    Us:    " + str(self._p2_wins))
        print("    Host:  " + str(self._p1_wins))
        print("    Draws: " + str(self._draws))
    
    def reset_board(self):
        self._board = ['1','2','3','4','5','6','7','8','9']
        self._step = -1
        self._move = 0
        self._input_waiting = False
    
    def is_winner(self, player_num):
        p = 'X'
        if player_num == 2:
            p = 'O'
        b = self._board
        if b[0] == b[1] == b[2] == p:
            return True
        elif b[3] == b[4] == b[5] == p:
            return True
        elif b[6] == b[7] == b[8] == p:
            return True
        elif b[0] == b[3] == b[6] == p:
            return True
        elif b[1] == b[4] == b[7] == p:
            return True
        elif b[2] == b[5] == b[8] == p:
            return True
        elif b[0] == b[4] == b[8] == p:
            return True
        elif b[2] == b[4] == b[6] == p:
            return True
        else:
            return False
    
    def is_board_full(self):
        for square in self._board:
            if square != 'X' and square != 'O':
                # still at least one square left to play...
                return False
        return True
    
    def print_board(self):
        b = self._board
        print("-------------")
        print(f"| {b[0]} | {b[1]} | {b[2]} |")
        print("-------------")
        print(f"| {b[3]} | {b[4]} | {b[5]} |")
        print("-------------")
        print(f"| {b[6]} | {b[7]} | {b[8]} |")
        print("-------------")        

               
    def is_connected(self):
        return self._conn_handle is not None
    
    def scan(self, callback=None):
        self._addr_type = None
        self._addr = None
        self._scan_callback = callback
        self._ble.gap_scan(2000, 30000, 30000)
        
    # TODO: remove the callback from connect?
    def connect(self, addr_type=None, addr=None, callback=None):
        self._addr_type = addr_type or self._addr_type
        self._addr = addr or self._addr
        # self._conn_callback = callback
        if self._addr_type is None or self._addr is None:
            return False
        self._ble.gap_connect(self._addr_type, self._addr)
        return True
    
    def disconnect(self):
        if not self._conn_handle:
            return
        self._ble.gap_disconnect(self._conn_handle)
        self._reset()

def game(ble, central):

    not_found = False
    
    def on_scan(addr_type, addr, name):
        if addr_type is not None:
            central.connect()
        else:
            nonlocal not_found
            not_found = True
            print("Searching for host...")
    
    if not central.is_connected():
        central.scan(callback=on_scan)
    
    while not central.is_connected():
        time.sleep_ms(100)
        if not_found:
            return
    
    if (central._starts + central._step) % 2 == 1 and central._input_waiting:
        move = -1
        if uselect.select([sys.stdin], [], [], 0.01)[0]:
            input_line = sys.stdin.readline().strip()
            try:
                move = int(input_line)
            except ValueError:
                pass
        if move != -1:
            if move >= 1 and move <= 9:
                central.make_move(move)
            else:
                print("That is not a valid move.  Please try again.")
    elif central._starts == -1 and central._step == -1 and central._conn_handle is not None and central._handle_game_state is not None:
        # on our first game, there isn't an event to push the game state to us, so let's request it
        try:
            central._ble.gattc_read(central._conn_handle, central._handle_game_state)
        except:
            # ignore any failures and keep trying...
            pass


if __name__ == "__main__":
    ble = bluetooth.BLE()
    central = TicTacToe(ble)
    while True:
        game(ble, central)
        time.sleep(1)