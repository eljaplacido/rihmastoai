# Requirements

- **MRB-001**: A person can book a free room for a time slot.
  - Given a free room, when Ella books it from 10.00 to 11.00, then the room shows as booked by Ella.
- **MRB-002**: A room cannot be booked twice for overlapping times.
  - Given a room booked from 10.00 to 11.00, when Leo books it from 10.30 to 11.30, then the booking is refused with the overlapping booking named.
