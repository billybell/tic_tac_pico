

import asyncio
import bluetooth
import random
import struct
import time
import uselect
import sys
from ble_advertising import advertising_payload

from micropython import const

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_INDICATE_DONE = const(20)

_FLAG_READ = const(0x0002)
_FLAG_WRITE = const(0x0008)
_FLAG_NOTIFY = const(0x0010)
_FLAG_INDICATE = const(0x0020)

_GAME_UUID = bluetooth.UUID("d314caba614b43c3a05fec9a48d85750")

_GAME_STATE_CHAR = (
    bluetooth.UUID("a3d11e79-dfe4-461a-83c1-da99f708018d"),
    _FLAG_READ | _FLAG_WRITE | _FLAG_NOTIFY,
)

_P2_MOVE_CHAR = (
    bluetooth.UUID("bd63370c-68b9-489d-ac8c-4715fa9b6a4f"),
    _FLAG_READ | _FLAG_WRITE | _FLAG_NOTIFY | _FLAG_INDICATE,
)

_GAME_SERVICE = (
    _GAME_UUID,
    (_GAME_STATE_CHAR,),
)


_ADV_APPEARANCE_GENERIC_GAMING = const(0x0A80)


class TicTacToe:
    def __init__(self, ble):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)
        ((self._handle_game_state,),) = self._ble.gatts_register_services((_GAME_SERVICE,))
        self._connections = set()
        self._payload = advertising_payload(
            name="tic", services=[_GAME_UUID], appearance=_ADV_APPEARANCE_GENERIC_GAMING
        )
        # self.reset_board()
        self._step = 0
        self._starts = 0
        self._advertise()
        

    def reset_board(self):
        self._board = ['1','2','3','4','5','6','7','8','9']
        self._step = 0
        # make who starts random and print who's starting this round
        self._starts = random.randint(0, 1)   # 0 = host, 1 = joined user
        self._step = 0
        self._move = 0
        if (self._starts + self._step) % 2 == 0:
            self._input_waiting = True
            print("We go first this time!")
        else:
            print("Guest goes first this time!")
            self._input_waiting = False
        self.write_instructions()


    def _irq(self, event, data):
        # Track connections so we can send notifications.
        if event == _IRQ_CENTRAL_CONNECT:
            print("Guest connected!")
            conn_handle, _, _ = data
            self._connections.add(conn_handle)
            self.new_player()
            self.reset_board()
            if (self._starts + self._step) % 2 == 0:
                self.get_p1_move()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            print("Goodbye guest!")
            conn_handle, _, _ = data
            self._connections.remove(conn_handle)
            # Start advertising again to allow a new connection.
            # TODO: does this mean we won't get a second connection?
            print("Waiting for guest to connect...")
            self._advertise()
        elif event == _IRQ_GATTS_INDICATE_DONE:
            conn_handle, value_handle, status = data
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if conn_handle in self._connections:
                    instructions = list(self._ble.gatts_read(self._handle_game_state).decode("UTF-8"))
                    if len(instructions) == 3:
                        starts = int(instructions.pop(0))
                        step = int(instructions.pop(0))
                        move = int(instructions.pop(0))
                        print(f"starts: {starts}, step: {step}, move: {move}")
                        if self._starts != starts:
                            print("Whoa, players changed starter?")
                        if self._step + 1 != step:
                            print(f"Did we miss a step?  Our last step was {self._step} but player 2 sent step {step}")
                        self._step = step
                        if (self._starts + self._step) % 2 == 0:  # 0 because it's our turn now - just capturing what p2 did
                            # handle connected players movement
                            # TODO: validate input before switching turns...
                            if self.is_free(move):
                                self._board[move - 1] = 'O'
                                print("Guest took square " + str(move))
                                if self.is_winner(2):
                                    print("Guest wins!")
                                    self._p2_wins += 1
                                    self.print_board()
                                    self.print_stats()
                                    self.reset_board()
                                    if (self._starts + self._step) % 2 == 0:
                                        # p1 was picked to start the next game
                                        self.get_p1_move()
                                elif self.is_board_full():
                                    print("It's a draw!!")
                                    self._draws += 1
                                    self.print_board()
                                    self.print_stats()
                                    self.reset_board()
                                    if (self._starts + self._step) % 2 == 0:
                                        # p1 was picked to start the next game
                                        self.get_p1_move()
                                else:
                                    self.get_p1_move()
                            
                            else:
                                print("Guest tried to take square " + str(move) + " but it's not free...")
                            
                        else:
                            print("Naughty!  Wait your turn!")
                    else:
                        print("Wrong number of instructions: " + str(len(instructions)))

                        
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
           
    def is_free(self, move):
        if self._board[move - 1] == str(move):
            return True
        else:
            return False
           
    def write_instructions(self):
        instructions = str(self._starts) + str(self._step) + str(self._move)
        self._ble.gatts_write(self._handle_game_state, instructions.encode("UTF-8"))
        for conn in self._connections:
            self._ble.gatts_notify(conn, self._handle_game_state)

           
    def make_move(self, move):
        #TODO check input and move the move
        if self.is_free(move):
            self._move = move
            self._step += 1
            self._board[move - 1] = 'X'
            self.write_instructions()
            if self.is_winner(1):
                print("We won!")
                self._p1_wins += 1
                self.print_board()
                self.print_stats()
                self.reset_board()
                if (self._starts + self._step) % 2 == 0:
                    self.get_p1_move()
            elif self.is_board_full():
                print("It's a draw!!")
                self._draws += 1
                self.print_board()
                self.print_stats()
                self.reset_board()
                if (self._starts + self._step) % 2 == 0:
                    self.get_p1_move()
            else:
                print("We took square " + str(move) + ".")
                self.print_board()
                print("Waiting for guest...")
                self._input_waiting = False
            
        else:
            print(f"Move {move} is not available, try again...")
            self.print_board()

    def print_stats(self):
        print("Stats so far:")
        print("    Us:    " + str(self._p1_wins))
        print("    Guest: " + str(self._p2_wins))
        print("    Draws: " + str(self._draws))

    def get_p1_move(self):
        self.print_board()
        print("What's your move (X)?")
        self.tell_turn()
        self._input_waiting = True

    def new_player(self):
        self._p1_wins = 0
        self._p2_wins = 0
        self._draws = 0
        self._input_waiting = False
        self._board = ['1','2','3','4','5','6','7','8','9']
        
    # TODO: rename
    def tell_turn(self):
        for conn_handle in self._connections:
            # Notify connected centrals.
            self._ble.gatts_notify(conn_handle, self._handle_game_state)


    def _advertise(self, interval_us=500000):
        self._ble.gap_advertise(interval_us, adv_data=self._payload)


def start():
    
    ble = bluetooth.BLE()

    game = TicTacToe(ble)

    # TODO: call new player only on connection?
    game.new_player()

    print("Running as host")
    print(f"Waiting for guest to join...")

    i = 0

    while True:
        # Write every second, notify every 10 seconds.
        i = (i + 1) % 10
        if i == 0:
            pass
            #game.tell_turn()
        
        if (game._starts + game._step) % 2 == 0 and game._input_waiting:
            move = -1
            if uselect.select([sys.stdin], [], [], 0.01)[0]:
                input_line = sys.stdin.readline().strip()
                try:
                    move = int(input_line)
                except ValueError:
                    pass
            
                if move != -1:
                    if move >= 1 and move <= 9:
                        game.make_move(move)
                    else:
                        print("That is not a valid move.  Please try again.")
        time.sleep_ms(1000)
        


if __name__ == "__main__":
    start()
