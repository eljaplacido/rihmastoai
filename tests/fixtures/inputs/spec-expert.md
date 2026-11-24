# Specification: Tool loan register

Author: the warehouse's systems specialist. Version 1.2.

## Goal

Lost tools cost the warehouse about 40 tools a year. The goal is to cut losses by half within six months of
launch; success is measured as tools reported missing per quarter.

## Users and roles

- Warehouse workers lend and return tools.
- Shift supervisors approve loans of tools worth more than 500 euros.

## Requirements

- **TLR-001**: A worker can register a tool with a name and an inventory number.
  - Given no tool with inventory number 77, when a worker registers "Drill" with number 77, then the register lists Drill with number 77.
- **TLR-002**: A loan records the borrower, the tool and a due date.
  - Given a registered tool, when a worker lends it to Mia with a due date, then the tool shows as lent to Mia until that date.
  - Given a lent tool, when another loan of it is attempted, then the register refuses it with a reason.
- **TLR-003**: A loan of a tool worth more than 500 euros needs a shift supervisor's approval.
  - Given a tool worth 800 euros, when a worker lends it without approval, then the loan waits for a supervisor.
- **TLR-004**: Overdue loans are listed for the shift supervisor every morning.
  - Given a loan past its due date, when the supervisor opens the overdue list, then the loan is on it with the borrower's name.

## Performance

The register answers within one second for up to 50 workers at once.
