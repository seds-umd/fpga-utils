package fpga_utils_tests

import spinal.core._
import spinal.lib._
import spinal.lib.bus.amba4.axis.{Axi4Stream, Axi4StreamConfig}

case class Color(channelWidth: Int) extends Bundle {
  val r, g, b = UInt(channelWidth bits)
}

// Hardware definition
case class StreamExample() extends Component {
  val axis_cfg = Axi4StreamConfig(16, userWidth = 1, useLast = true, useUser = true)

  val io = new Bundle {
    val a_in = slave Stream (Bits(8 bits))
    val a_out = master Stream (Bits(8 bits))

    val b_in = slave Stream Fragment(SInt(16 bits))
    val b_out = master Stream Fragment(SInt(16 bits))

    val c_in = slave Stream (Color(2))
    val c_out = master Stream (Color(2))

    val d_in = slave Stream Fragment(Color(2))
    val d_out = master Stream Fragment(Color(2))

    // val e_in = slave(Axi4Stream(axis_cfg))
    // val e_out = master(Axi4Stream(axis_cfg))

    val f_in = slave Flow (Bits(64 bits))
    val f_out = master Flow (Bits(64 bits))

    val g_in = slave Flow Fragment(Bits(1 bits))
    val g_out = master Flow Fragment(Bits(1 bits))
  }

  // Register both directions
  io.a_out <-/< io.a_in
  io.b_out <-/< io.b_in
  io.c_out <-/< io.c_in
  io.d_out <-/< io.d_in
  // io.e_out <-/< io.e_in
  io.f_out <-< io.f_in
  io.g_out <-< io.g_in
}

object StreamExampleVerilog extends App {
  Config.spinal.generateVerilog(StreamExample())
}
