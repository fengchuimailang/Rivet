module fifo #(
    parameter int DATA_WIDTH = 8,
    parameter int DEPTH = 4
) (
    input  logic                  clk,
    input  logic                  rst,
    input  logic                  wr_en,
    input  logic                  rd_en,
    input  logic [DATA_WIDTH-1:0] w_data,
    output logic [DATA_WIDTH-1:0] r_data,
    output logic                  full,
    output logic                  empty
);
    localparam int PTR_WIDTH = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
    localparam int COUNT_WIDTH = $clog2(DEPTH + 1);

    logic [DATA_WIDTH-1:0] storage [0:DEPTH-1];
    logic [PTR_WIDTH-1:0] wr_ptr;
    logic [PTR_WIDTH-1:0] rd_ptr;
    logic [COUNT_WIDTH-1:0] count;

    initial begin
        if (DATA_WIDTH < 1) $fatal(1, "DATA_WIDTH must be at least 1");
        if (DEPTH < 1) $fatal(1, "DEPTH must be at least 1");
    end

    assign empty = (count == 0);
    assign full = (count == DEPTH);

    function automatic [PTR_WIDTH-1:0] next_ptr(input [PTR_WIDTH-1:0] ptr);
        if (ptr == DEPTH - 1)
            next_ptr = '0;
        else
            next_ptr = ptr + 1'b1;
    endfunction

    always_ff @(posedge clk) begin
        if (rst) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
            count <= '0;
            r_data <= '0;
        end else begin
            case ({wr_en && !full, rd_en && !empty})
                2'b10: begin
                    storage[wr_ptr] <= w_data;
                    wr_ptr <= next_ptr(wr_ptr);
                    count <= count + 1'b1;
                end
                2'b01: begin
                    r_data <= storage[rd_ptr];
                    rd_ptr <= next_ptr(rd_ptr);
                    count <= count - 1'b1;
                end
                2'b11: begin
                    storage[wr_ptr] <= w_data;
                    wr_ptr <= next_ptr(wr_ptr);
                    r_data <= storage[rd_ptr];
                    rd_ptr <= next_ptr(rd_ptr);
                end
                default: begin
                end
            endcase
        end
    end
endmodule
